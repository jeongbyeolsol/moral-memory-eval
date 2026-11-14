import hashlib
import json
import sys
from pathlib import Path

import pytest

from llmkit import DataError, GenerationConfig, LLMRequest
from llmkit.io import load_jsonl, save_json, save_jsonl
from moral_memory_eval import _storage, cli, creak, sampling
from moral_memory_eval._storage import canonical_hash, sha256_file
from moral_memory_eval.creak import load_creak
from moral_memory_eval.preparation import (
    build_cases,
    prepare_requests,
    select_profiles,
    verify_prepared,
)
from moral_memory_eval.sampling import (
    load_selection,
    metadata_path,
    sample_and_save,
    sample_claims,
    verify_disjoint,
)
from moral_memory_eval.schemas import (
    ManifestEntry,
    Profile,
    Profiles,
)


@pytest.fixture
def artifacts(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    source = raw / "dev.json"
    rows = [
        {
            "ex_id": f"{label}-{i}",
            "sentence": f"Original {label} sentence {i}.",
            "label": label,
            "explanation": "SECRET explanation",
            "entity": "Metadata",
        }
        for label in ("true", "false")
        for i in range(10)
    ]
    source.write_text("\n\n".join(json.dumps(row) for row in rows) + "\n")
    selected = tmp_path / "selected" / "pilot.jsonl"
    sample_and_save(source, selected, n_true=3, n_false=2, seed=42)
    profiles = Profiles(
        profiles=[
            Profile(id="no_profile", memory=None, candidate_score=None),
            Profile(id="p0", memory="The user has harmed others.", candidate_score=0),
            Profile(id="p5", memory="The user has helped others.", candidate_score=5),
        ]
    )
    profile_path = tmp_path / "profiles.json"
    save_json(profile_path, profiles)
    return source, selected, profile_path, profiles


def prepare(artifacts, output, **kwargs):
    _, selected, profiles_path, _ = artifacts
    return prepare_requests(selected, profiles_path, ["p0", "p5", "no_profile"], output, **kwargs)


def test_raw_symlink_read_is_nonmutating(tmp_path):
    target = tmp_path / "external"
    target.mkdir()
    source = target / "dev.json"
    raw = b'{"ex_id":"one","sentence":"Unmodified sentence.","label":"false"}\n'
    source.write_bytes(raw)
    link = tmp_path / "creak"
    link.symlink_to(target, target_is_directory=True)
    destination = tmp_path / "selected" / "claims.jsonl"
    meta = sample_and_save(link / "dev.json", destination, n_true=0, n_false=1, seed=0)
    claims, _ = load_selection(destination)
    assert claims[0].expected is False
    assert claims[0].sentence == "Unmodified sentence."
    assert meta.source_sha256 == hashlib.sha256(raw).hexdigest()
    assert source.read_bytes() == raw
    assert link.is_symlink() and link.readlink() == target
    assert list(target.iterdir()) == [source]
    with pytest.raises(DataError, match="raw source"):
        sample_and_save(link / "dev.json", link / "new.jsonl", n_true=0, n_false=1, seed=0)
    assert list(target.iterdir()) == [source]


@pytest.mark.parametrize(
    "text",
    [
        "not JSON",
        "{}",
        '{"ex_id":"a","sentence":"","label":"true"}',
        '{"ex_id":"a","sentence":"x","label":true}',
        '{"ex_id":"a","sentence":"x","label":"unknown"}',
        '{"sentence":"x","label":"false"}',
    ],
)
def test_bad_raw_creak_rejected(tmp_path, text):
    source = tmp_path / "dev.json"
    source.write_text(text)
    with pytest.raises(DataError, match="dev.json:1"):
        load_creak(source, "dev")


def test_duplicate_raw_ids_rejected(tmp_path):
    source = tmp_path / "dev.json"
    row = '{"ex_id":"a","sentence":"x","label":"true"}\n'
    source.write_text(row + row)
    with pytest.raises(DataError, match="unique"):
        load_creak(source, "dev")


@pytest.mark.parametrize("n_true,n_false", [(3, 4), (0, 4), (4, 0)])
def test_exact_counts_seed_uniqueness_and_exclusions(artifacts, n_true, n_false):
    source, *_ = artifacts
    claims = load_creak(source, "dev")
    excluded = {claims[0].id, claims[-1].id}
    a = sample_claims(claims, n_true, n_false, 17, excluded)
    b = sample_claims(claims, n_true, n_false, 17, excluded)
    assert a == b
    assert sum(row.expected for row in a) == n_true
    assert sum(not row.expected for row in a) == n_false
    assert len({row.id for row in a}) == len(a)
    assert not ({row.id for row in a} & excluded)


@pytest.mark.parametrize("n_true,n_false", [(0, 0), (-1, 2), (100, 2), (2, 100), (True, 1)])
def test_invalid_sampling_counts(artifacts, n_true, n_false):
    with pytest.raises(DataError):
        sample_claims(load_creak(artifacts[0], "dev"), n_true, n_false, 42)


def test_metadata_and_pilot_exclusion(artifacts, tmp_path):
    source, selected, *_ = artifacts
    claims, meta = load_selection(selected)
    assert meta.selected_ids == [claim.id for claim in claims]
    assert meta.n_true == 3 and meta.n_false == 2
    assert meta.selected_sha256 == sha256_file(selected)
    assert meta.source_sha256 == sha256_file(source)
    assert meta.excluded_ids == []
    main = tmp_path / "selected" / "main.jsonl"
    sample_and_save(source, main, n_true=3, n_false=3, seed=42, exclude_claims=[selected])
    _, main_meta = load_selection(main)
    assert set(main_meta.excluded_ids) == set(meta.selected_ids)
    verify_disjoint(selected, main)
    with pytest.raises(DataError, match="Overlapping"):
        verify_disjoint(selected, selected)


def test_selection_hash_and_metadata_semantics_detect_tampering(artifacts):
    _, selected, *_ = artifacts
    claims, meta = load_selection(selected)
    original = selected.read_bytes()
    selected.write_bytes(original + b"\n")
    with pytest.raises(DataError, match="SHA-256"):
        load_selection(selected)
    selected.write_bytes(original)
    save_json(metadata_path(selected), meta.model_copy(update={"n_true": 2, "n_false": 3}))
    with pytest.raises(DataError, match="label counts"):
        load_selection(selected)


def test_selection_missing_metadata_is_not_accepted(artifacts, tmp_path):
    copied = tmp_path / "alone.jsonl"
    copied.write_bytes(artifacts[1].read_bytes())
    with pytest.raises(DataError):
        load_selection(copied)


def test_existing_selection_or_metadata_never_overwritten(artifacts, tmp_path):
    source, selected, *_ = artifacts
    before = selected.read_bytes(), metadata_path(selected).read_bytes()
    with pytest.raises(DataError, match="exists"):
        sample_and_save(source, selected, n_true=1, n_false=1, seed=1)
    assert (selected.read_bytes(), metadata_path(selected).read_bytes()) == before
    target = tmp_path / "selected" / "blocked.jsonl"
    metadata_path(target).write_text("keep this file")
    with pytest.raises(DataError, match="exists"):
        sample_and_save(source, target, n_true=1, n_false=1, seed=1)
    assert not target.exists()
    assert metadata_path(target).read_text() == "keep this file"


def test_selection_staging_failure_leaves_no_partial_pair(artifacts, tmp_path, monkeypatch):
    source = artifacts[0]
    output = tmp_path / "selected" / "failed.jsonl"

    def fail(*args, **kwargs):
        raise DataError("simulated metadata write failure")

    monkeypatch.setattr(sampling, "save_json", fail)
    with pytest.raises(DataError, match="simulated"):
        sample_and_save(source, output, n_true=1, n_false=1, seed=1)
    assert not output.exists() and not metadata_path(output).exists()
    assert not list(output.parent.glob(".sample-*"))
    load_selection(artifacts[1])


def test_selection_publication_failure_rolls_back_own_file(artifacts, tmp_path, monkeypatch):
    output = tmp_path / "selected" / "failed.jsonl"
    original_link = _storage.os.link

    def fail_second(source, destination):
        if Path(destination) == metadata_path(output):
            raise OSError("simulated second publication failure")
        original_link(source, destination)

    monkeypatch.setattr(_storage.os, "link", fail_second)
    with pytest.raises(DataError, match="simulated"):
        sample_and_save(artifacts[0], output, n_true=1, n_false=1, seed=1)
    assert not output.exists() and not metadata_path(output).exists()
    load_selection(artifacts[1])


def test_selected_profiles_and_duplicate_validation(artifacts):
    profiles = artifacts[3]
    assert [p.id for p in select_profiles(profiles, ["p5", "no_profile"]).profiles] == [
        "p5",
        "no_profile",
    ]
    for ids in ([], ["p0", "p0"], ["missing"]):
        with pytest.raises(DataError):
            select_profiles(profiles, ids)


def test_prepared_counts_defaults_and_file_chat_compatibility(artifacts, tmp_path):
    from examples.file_chat import load_requests

    output = tmp_path / "generated"
    meta = prepare(artifacts, output, repeats=2, seed=42)
    requests = load_requests(output / "requests.jsonl")
    entries = load_jsonl(output / "manifest.jsonl", ManifestEntry)
    assert len(requests) == len(entries) == meta.case_count == 5 * 3 * 2
    assert len({row.trial_id for row in entries}) == meta.case_count
    assert {row.repeat_index for row in entries} == {0, 1}
    assert [row.request_index for row in entries] == list(range(meta.case_count))
    assert all(request.generation.max_output_tokens == 256 for request in requests)
    assert all(request.generation.temperature is None for request in requests)
    assert all(
        canonical_hash(request) == row.request_sha256 for request, row in zip(requests, entries)
    )
    assert verify_prepared(output) == meta
    assert set(path.name for path in output.iterdir()) == {
        "requests.jsonl",
        "manifest.jsonl",
        "preparation.json",
    }


def test_stable_ids_order_and_file_bytes(artifacts, tmp_path):
    a, b = tmp_path / "one", tmp_path / "two"
    prepare(artifacts, a, repeats=2, seed=51)
    prepare(artifacts, b, repeats=2, seed=51)
    for name in ("requests.jsonl", "manifest.jsonl", "preparation.json"):
        assert (a / name).read_bytes() == (b / name).read_bytes()
    settings = verify_prepared(a).settings
    _, fixed = build_cases(settings.model_copy(update={"seed": None}))
    assert [row.profile_id for row in fixed[:6]] == [
        "p0",
        "p0",
        "p5",
        "p5",
        "no_profile",
        "no_profile",
    ]
    _, shuffled = build_cases(settings)
    assert [(r.claim_id, r.profile_id, r.repeat_index) for r in shuffled] != [
        (r.claim_id, r.profile_id, r.repeat_index) for r in fixed
    ]


def test_profile_subset_generation_and_metadata_do_not_leak(artifacts, tmp_path):
    _, selected, profiles_path, _ = artifacts
    output = tmp_path / "subset"
    meta = prepare_requests(
        selected,
        profiles_path,
        ["p5", "no_profile"],
        output,
        generation=GenerationConfig(max_output_tokens=128, temperature=0.2),
    )
    entries = load_jsonl(output / "manifest.jsonl", ManifestEntry)
    requests = load_jsonl(output / "requests.jsonl", LLMRequest)
    assert len(requests) == 10
    assert {entry.profile_id for entry in entries} == {"p5", "no_profile"}
    assert meta.settings.generation == GenerationConfig(max_output_tokens=128, temperature=0.2)
    for request, entry in zip(requests, entries):
        text = request.model_dump_json()
        for forbidden in (
            "candidate_score",
            "expected",
            "claim_id",
            "profile_id",
            "trial_id",
            "SECRET",
            '"explanation":',
            "CREAK",
        ):
            assert forbidden not in text
        if entry.profile_id == "no_profile":
            assert "None available." in request.messages[0].content
    changed = meta.settings.model_copy(
        update={
            "profiles": Profiles(
                profiles=[
                    p.model_copy(update={"candidate_score": 3})
                    for p in meta.settings.profiles.profiles
                ]
            ),
            "claims": [
                c.model_copy(update={"expected": not c.expected}) for c in meta.settings.claims
            ],
        }
    )
    assert build_cases(changed)[0] == requests


def test_prepare_does_not_read_or_sample_raw_source(artifacts, tmp_path, monkeypatch):
    raw_source = artifacts[0]
    original_bytes = raw_source.read_bytes()
    original_open = Path.open

    def guarded_open(path, *args, **kwargs):
        if path.resolve() == raw_source.resolve():
            pytest.fail("Preparation attempted to read raw CREAK")
        return original_open(path, *args, **kwargs)

    def forbidden(*args, **kwargs):
        pytest.fail("Preparation attempted to resample or reload raw CREAK")

    monkeypatch.setattr(Path, "open", guarded_open)
    monkeypatch.setattr(sampling, "sample_claims", forbidden)
    monkeypatch.setattr(sampling, "read_creak_snapshot", forbidden)
    monkeypatch.setattr(creak, "read_creak_snapshot", forbidden)
    meta = prepare(artifacts, tmp_path / "prepared")
    assert meta.case_count == 15
    with original_open(raw_source, "rb") as stream:
        assert stream.read() == original_bytes


def test_existing_generated_directory_preserved(artifacts, tmp_path):
    output = tmp_path / "existing"
    output.mkdir()
    sentinel = output / "requests.jsonl"
    sentinel.write_text("keep")
    with pytest.raises(DataError, match="exists"):
        prepare(artifacts, output)
    assert list(output.iterdir()) == [sentinel]
    assert sentinel.read_text() == "keep"
    empty = tmp_path / "empty-existing"
    empty.mkdir()
    with pytest.raises(DataError, match="exists"):
        prepare(artifacts, empty)


def test_directory_publication_failure_removes_only_reservation(artifacts, tmp_path, monkeypatch):
    output = tmp_path / "failed"
    original_replace = _storage.os.replace

    def fail_directory(source, destination):
        if Path(source).is_dir():
            raise OSError("simulated directory publication failure")
        original_replace(source, destination)

    monkeypatch.setattr(_storage.os, "replace", fail_directory)
    with pytest.raises(DataError, match="simulated"):
        prepare(artifacts, output)
    assert not output.exists()
    assert not list(tmp_path.glob(".prepare-*"))
    load_selection(artifacts[1])


@pytest.mark.parametrize("filename", ["requests.jsonl", "manifest.jsonl"])
def test_prepared_hash_detects_any_file_change(artifacts, tmp_path, filename):
    output = tmp_path / "generated"
    prepare(artifacts, output)
    with (output / filename).open("a") as stream:
        stream.write("\n")
    with pytest.raises(DataError, match="SHA-256"):
        verify_prepared(output)


def test_manifest_semantics_checked_even_when_file_hash_updated(artifacts, tmp_path):
    output = tmp_path / "generated"
    meta = prepare(artifacts, output)
    entries = load_jsonl(output / "manifest.jsonl", ManifestEntry)
    entries[0] = entries[0].model_copy(update={"expected": not entries[0].expected})
    save_jsonl(output / "manifest.jsonl", entries)
    save_json(
        output / "preparation.json",
        meta.model_copy(
            update={
                "manifest_sha256": sha256_file(output / "manifest.jsonl"),
            }
        ),
    )
    with pytest.raises(DataError, match="content or order"):
        verify_prepared(output)


def test_request_count_checked_even_when_file_hash_updated(artifacts, tmp_path):
    output = tmp_path / "generated"
    meta = prepare(artifacts, output)
    requests = load_jsonl(output / "requests.jsonl", LLMRequest)
    save_jsonl(output / "requests.jsonl", requests[:-1])
    save_json(
        output / "preparation.json",
        meta.model_copy(
            update={
                "requests_sha256": sha256_file(output / "requests.jsonl"),
            }
        ),
    )
    with pytest.raises(DataError, match="count mismatch"):
        verify_prepared(output)


def test_cli_offline_workflow_and_error_exit(artifacts, tmp_path, monkeypatch, capsys):
    source, selected, profiles_path, _ = artifacts
    output = tmp_path / "cli-selection" / "claims.jsonl"
    commands = [
        [
            "sample",
            "--source",
            str(source),
            "--n-true",
            "2",
            "--n-false",
            "2",
            "--seed",
            "2",
            "--exclude-claims",
            str(selected),
            "--output",
            str(output),
        ],
        [
            "verify-selection",
            "--claims",
            str(output),
            "--against",
            str(selected),
            "--source",
            str(source),
        ],
        [
            "prepare",
            "--claims",
            str(output),
            "--profiles",
            str(profiles_path),
            "--profile-ids",
            "no_profile",
            "p5",
            "--repeats",
            "2",
            "--seed",
            "2",
            "--output-dir",
            str(tmp_path / "cli-generated"),
        ],
        ["verify-prepared", "--input-dir", str(tmp_path / "cli-generated")],
    ]
    for command in commands:
        monkeypatch.setattr(sys, "argv", ["cli", *command])
        cli.main()
    assert verify_prepared(tmp_path / "cli-generated").case_count == 16
    assert "no API calls" in capsys.readouterr().out
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "cli",
            "sample",
            "--source",
            str(source),
            "--n-true",
            "1000",
            "--n-false",
            "1",
            "--seed",
            "2",
            "--output",
            str(tmp_path / "impossible.jsonl"),
        ],
    )
    with pytest.raises(SystemExit) as caught:
        cli.main()
    assert caught.value.code == 1
    assert "DataError" in capsys.readouterr().err
