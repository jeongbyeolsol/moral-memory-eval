import fcntl
import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from llmkit import ClientConfig, DataError, LLMClient, LLMResponse, ProviderError
from llmkit.errors import StructuredOutputError
from llmkit.io import load_json, load_jsonl, save_json, save_jsonl
from moral_memory_eval import cli, execution, preparation
from moral_memory_eval._storage import sha256_file
from moral_memory_eval.analysis import analyze_results, analyze_run
from moral_memory_eval.execution import (
    ExecutionError,
    load_prepared_inputs,
    load_run,
    preview_run,
    run_metadata_path,
    run_prepared,
)
from moral_memory_eval.preparation import prepare_requests, verify_prepared
from moral_memory_eval.sampling import sample_and_save
from moral_memory_eval.schemas import (
    ManifestEntry,
    PreparedAnalysis,
    PreparedResult,
    Profile,
    Profiles,
    Verdict,
)


class RecordingProvider:
    def __init__(self, answers=None, fail_after=None):
        self.calls = []
        self.answers = answers
        self.fail_after = fail_after
        self.closed = False

    def generate(self, request, *, response_model=None):
        if self.fail_after == len(self.calls):
            raise ProviderError("openai", status_code=429)
        index = len(self.calls)
        self.calls.append((request, response_model))
        text = (
            self.answers[index]
            if self.answers is not None
            else '{"is_true":false,"confidence":0.8}'
        )
        return LLMResponse(provider="openai", model="test-snapshot", text=text)

    def close(self):
        self.closed = True


def make_client(provider, model="test"):
    return LLMClient(ClientConfig(provider="openai", model=model, max_retries=0), provider=provider)


@pytest.fixture
def prepared(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    source = raw / "dev.json"
    source.write_text(
        "\n".join(
            [
                '{"ex_id":"t","sentence":"True sentence.","label":"true","explanation":"SECRET"}',
                '{"ex_id":"f","sentence":"False sentence.","label":"false"}',
            ]
        )
    )
    selected = tmp_path / "selected" / "claims.jsonl"
    sample_and_save(source, selected, n_true=1, n_false=1, seed=42)
    profiles = tmp_path / "profiles.json"
    save_json(
        profiles,
        Profiles(
            profiles=[
                Profile(id="no_profile", memory=None, candidate_score=None),
                Profile(id="moral", memory="The user helps others.", candidate_score=5),
            ]
        ),
    )
    directory = tmp_path / "prepared"
    prepare_requests(selected, profiles, ["no_profile", "moral"], directory, repeats=2, seed=17)
    return directory


def execute(prepared, output, provider=None, **kwargs):
    fake = provider if provider is not None else RecordingProvider()
    with make_client(fake) as client:
        saved = run_prepared(client, prepared, output, **kwargs)
    return fake, saved


def test_prepared_requests_are_executed_exactly_and_all_metadata_matches(
    prepared, tmp_path, monkeypatch
):
    metadata, requests, entries = load_prepared_inputs(prepared)

    def forbidden(*args, **kwargs):
        pytest.fail("Execution must not rebuild prompts or case requests")

    monkeypatch.setattr(preparation, "build_cases", forbidden)
    monkeypatch.setattr(preparation, "build_request", forbidden)
    # Both snapshot paths may be unavailable; execution must still work offline with a mock.
    Path(metadata.selection_path).unlink()
    Path(metadata.profiles_path).unlink()
    output = tmp_path / "results.jsonl"
    provider, saved = execute(prepared, output)
    assert saved == metadata.case_count == 8
    assert provider.closed
    assert [request for request, _ in provider.calls] == requests
    assert all(model is Verdict for _, model in provider.calls)
    run, rows = load_run(output)
    assert run.manifest == entries
    assert len({row.run_id for row in rows}) == 1
    for request, entry, row in zip(requests, entries, rows):
        assert row.request == request
        assert row.trial_id == entry.trial_id
        assert row.request_index == entry.request_index
        assert row.claim_id == entry.claim_id
        assert row.profile_id == entry.profile_id
        assert row.repeat_index == entry.repeat_index
        assert row.expected == entry.expected
        assert row.prompt_version == entry.prompt_version
        assert row.request_sha256 == entry.request_sha256
        assert row.response.model == "test-snapshot"
        assert row.verdict == row.response.parse(Verdict)
        assert "candidate_score" not in row.request.model_dump_json()
        assert "SECRET" not in row.request.model_dump_json()
    summary = analyze_run(output)
    assert summary.complete
    assert summary.pending_trial_ids == []
    assert set(summary.completed_trial_ids) == {entry.trial_id for entry in entries}


@pytest.mark.parametrize("filename", ["requests.jsonl", "manifest.jsonl"])
def test_tampered_inputs_rejected_before_any_api_or_result_creation(prepared, tmp_path, filename):
    with (prepared / filename).open("a") as stream:
        stream.write("\n")
    provider = RecordingProvider()
    output = tmp_path / "results.jsonl"
    with pytest.raises(DataError, match="SHA-256"):
        execute(prepared, output, provider)
    assert provider.calls == []
    assert not output.exists() and not run_metadata_path(output).exists()


def test_wrong_manifest_semantics_rejected_even_when_digest_updated(prepared, tmp_path):
    metadata = verify_prepared(prepared)
    entries = load_jsonl(prepared / "manifest.jsonl", ManifestEntry)
    entries[0] = entries[0].model_copy(update={"expected": not entries[0].expected})
    save_jsonl(prepared / "manifest.jsonl", entries)
    save_json(
        prepared / "preparation.json",
        metadata.model_copy(
            update={
                "manifest_sha256": sha256_file(prepared / "manifest.jsonl"),
            }
        ),
    )
    provider = RecordingProvider()
    with pytest.raises(DataError, match="content or order"):
        execute(prepared, tmp_path / "results.jsonl", provider)
    assert provider.calls == []


def test_failure_then_resume_only_pending_trials(prepared, tmp_path):
    _, requests, entries = load_prepared_inputs(prepared)
    output = tmp_path / "results.jsonl"
    first = RecordingProvider(fail_after=2)
    with pytest.raises(ExecutionError, match=entries[2].trial_id) as caught:
        execute(prepared, output, first)
    assert isinstance(caught.value.__cause__, ProviderError)
    assert caught.value.__cause__.status_code == 429
    before = output.read_bytes()
    initial_run, initial_rows = load_run(output)
    assert len(initial_rows) == 2
    assert not analyze_run(output).complete
    assert len(analyze_run(output).pending_trial_ids) == 6
    second, saved = execute(prepared, output, resume=True)
    assert saved == 6
    assert [request for request, _ in second.calls] == requests[2:]
    assert output.read_bytes().startswith(before)
    final_run, rows = load_run(output)
    assert final_run.run_id == initial_run.run_id
    assert [row.trial_id for row in rows] == [entry.trial_id for entry in entries]
    assert analyze_run(output).complete
    third, saved = execute(prepared, output, resume=True)
    assert saved == 0 and third.calls == []
    assert len(load_run(output)[1]) == 8


@pytest.mark.parametrize(
    "bad",
    [
        "invalid JSON",
        '{"is_true":false,"confidence":2}',
        '{"is_true":"false","confidence":0.9}',
        '{"is_true":false,"confidence":0.9,"reasoning":"extra"}',
    ],
)
def test_invalid_verdict_is_never_saved(prepared, tmp_path, bad):
    output = tmp_path / "results.jsonl"
    provider = RecordingProvider(answers=['{"is_true":false,"confidence":0.9}', bad])
    with pytest.raises(ExecutionError, match="StructuredOutputError") as caught:
        execute(prepared, output, provider)
    assert isinstance(caught.value.__cause__, StructuredOutputError)
    assert len(load_run(output)[1]) == 1
    assert analyze_run(output).observed_trials == 1


def test_existing_files_preserved_and_resume_is_explicit(prepared, tmp_path):
    output = tmp_path / "results.jsonl"
    execute(prepared, output, max_calls=1)
    before = output.read_bytes(), run_metadata_path(output).read_bytes()
    provider = RecordingProvider()
    with pytest.raises(DataError, match="exists"):
        execute(prepared, output, provider)
    assert provider.calls == []
    assert (output.read_bytes(), run_metadata_path(output).read_bytes()) == before


def test_resume_rejects_different_model_and_preparation(prepared, tmp_path):
    output = tmp_path / "results.jsonl"
    execute(prepared, output, max_calls=1)
    before = output.read_bytes()
    fake = RecordingProvider()
    with make_client(fake, model="different") as client, pytest.raises(DataError, match="original"):
        run_prepared(client, prepared, output, resume=True)
    metadata, _, _ = load_prepared_inputs(prepared)
    other = tmp_path / "other-input"
    prepare_requests(Path(metadata.selection_path), Path(metadata.profiles_path), ["moral"], other)
    with pytest.raises(DataError, match="does not match"):
        execute(other, output, fake, resume=True)
    assert fake.calls == [] and output.read_bytes() == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("expected", True),
        ("profile_id", "wrong"),
        ("claim_id", "wrong"),
        ("repeat_index", 100),
        ("request_index", 100),
        ("trial_id", "f" * 64),
    ],
)
def test_bad_result_mapping_rejected_for_resume_and_analysis(prepared, tmp_path, field, value):
    output = tmp_path / "results.jsonl"
    execute(prepared, output, max_calls=1)
    _, rows = load_run(output)
    if field == "expected":
        value = not rows[0].expected
    changed = rows[0].model_copy(update={field: value})
    save_jsonl(output, [changed])
    before = output.read_bytes()
    fake = RecordingProvider()
    with pytest.raises(DataError):
        execute(prepared, output, fake, resume=True)
    with pytest.raises(DataError):
        analyze_run(output)
    assert fake.calls == [] and output.read_bytes() == before


def test_duplicates_and_foreign_trials_cannot_fake_completion(prepared, tmp_path):
    output = tmp_path / "results.jsonl"
    execute(prepared, output)
    run, rows = load_run(output)
    # Same record count as a complete run, but the set contains a duplicate and misses a trial.
    with pytest.raises(DataError, match="Duplicate"):
        analyze_results(run, rows[:-1] + [rows[0]])
    with pytest.raises(DataError, match="Unplanned"):
        analyze_results(run, rows[:-1] + [rows[-1].model_copy(update={"trial_id": "a" * 64})])
    assert not analyze_results(run, rows[:-1]).complete


def test_truncated_log_is_rejected_without_repair_or_recalling(prepared, tmp_path):
    output = tmp_path / "results.jsonl"
    execute(prepared, output, max_calls=1)
    with output.open("a") as stream:
        stream.write('{"schema_version":"1.0","data":')
    before = output.read_bytes()
    fake = RecordingProvider()
    with pytest.raises(DataError):
        execute(prepared, output, fake, resume=True)
    assert output.read_bytes() == before and fake.calls == []


def test_empty_run_after_first_failure_is_resumable_and_has_no_invented_metrics(prepared, tmp_path):
    output = tmp_path / "results.jsonl"
    with pytest.raises(ExecutionError):
        execute(prepared, output, RecordingProvider(fail_after=0))
    summary = analyze_run(output)
    assert summary.observed_trials == 0
    assert summary.overall is None
    assert summary.by_profile == {}
    assert not summary.complete
    execute(prepared, output, resume=True)
    assert analyze_run(output).complete


def test_accuracy_and_correctness_brier_on_shuffled_manifest(prepared, tmp_path):
    _, _, entries = load_prepared_inputs(prepared)
    correct = [True, False, False, True, True, False, False, True]
    confidence = [0.9, 0.8, 0.6, 0.7] * 2
    answers = [
        json.dumps(
            {
                "is_true": entry.expected if right else not entry.expected,
                "confidence": prob,
            }
        )
        for entry, right, prob in zip(entries, correct, confidence)
    ]
    output = tmp_path / "results.jsonl"
    execute(prepared, output, RecordingProvider(answers=answers))
    summary = analyze_run(output)
    assert summary.complete
    assert summary.overall.accuracy == 0.5
    assert summary.overall.brier_score == pytest.approx(0.275)
    assert summary.overall.mean_confidence == pytest.approx(0.75)
    assert sum(score.count for score in summary.by_profile.values()) == 8
    _, rows = load_run(output)
    false_rows = [row for row in rows if not row.expected]
    assert summary.overall.false_claim_agreement_rate == sum(
        row.verdict.is_true for row in false_rows
    ) / len(false_rows)


def test_single_writer_lock_prevents_duplicate_concurrent_resume(prepared, tmp_path):
    output = tmp_path / "results.jsonl"
    execute(prepared, output, max_calls=1)
    before = output.read_bytes()
    fake = RecordingProvider()
    with output.with_suffix(".jsonl.lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(DataError, match="Another process"):
            execute(prepared, output, fake, resume=True)
    assert fake.calls == [] and output.read_bytes() == before


def test_save_failure_exposes_trial_and_preserves_prior_results(prepared, tmp_path, monkeypatch):
    output = tmp_path / "results.jsonl"
    real_append = execution.append_jsonl
    calls = 0

    def fail_second(path, value):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise DataError("simulated disk failure")
        real_append(path, value)

    monkeypatch.setattr(execution, "append_jsonl", fail_second)
    with pytest.raises(ExecutionError, match="simulated disk failure"):
        execute(prepared, output)
    assert len(load_run(output)[1]) == 1


def test_result_model_rejects_changed_request_and_verdict(prepared, tmp_path):
    output = tmp_path / "results.jsonl"
    execute(prepared, output, max_calls=1)
    _, rows = load_run(output)
    payload = rows[0].model_dump()
    payload["verdict"]["confidence"] = 0.1
    with pytest.raises(ValidationError, match="Verdict must match"):
        PreparedResult.model_validate(payload)
    payload = rows[0].model_dump()
    payload["request"]["messages"][1]["content"] = "tampered"
    with pytest.raises(ValidationError, match="SHA-256"):
        PreparedResult.model_validate(payload)


def test_cli_dry_run_needs_no_key_or_model(prepared, tmp_path, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("Dry run must not construct any API client")

    monkeypatch.setattr(cli, "LLMClient", forbidden)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    output = tmp_path / "results.jsonl"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "cli",
            "run",
            "--input-dir",
            str(prepared),
            "--provider",
            "openai",
            "--output",
            str(output),
            "--dry-run",
        ],
    )
    cli.main()
    assert "pending=8" in capsys.readouterr().out
    assert not output.exists() and not run_metadata_path(output).exists()


def test_cli_mock_execution_resume_and_offline_analysis(prepared, tmp_path, monkeypatch, capsys):
    provider = RecordingProvider()
    monkeypatch.setattr(cli, "LLMClient", lambda config: LLMClient(config, provider=provider))
    monkeypatch.setattr(cli, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("OPENAI_MODEL", "test")
    output = tmp_path / "results.jsonl"
    base = [
        "cli",
        "run",
        "--input-dir",
        str(prepared),
        "--provider",
        "openai",
        "--output",
        str(output),
        "--max-retries",
        "0",
    ]
    monkeypatch.setattr(sys, "argv", [*base, "--max-calls", "2"])
    cli.main()
    assert len(provider.calls) == 2
    monkeypatch.setattr(sys, "argv", [*base, "--resume"])
    cli.main()
    assert len(provider.calls) == 8
    summary_path = tmp_path / "summary.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "cli",
            "analyze",
            "--results",
            str(output),
            "--output",
            str(summary_path),
        ],
    )
    cli.main()
    assert load_json(summary_path, PreparedAnalysis).complete
    assert "Saved 6 new results" in capsys.readouterr().out
    before = summary_path.read_bytes()
    with pytest.raises(SystemExit):
        cli.main()
    assert summary_path.read_bytes() == before


def test_preview_and_output_safety(prepared, tmp_path):
    output = tmp_path / "results.jsonl"
    assert preview_run(prepared, output) == (8, 0)
    execute(prepared, output, max_calls=3)
    assert preview_run(prepared, output, resume=True) == (8, 3)
    fake = RecordingProvider()
    with pytest.raises(DataError, match="outside"):
        execute(prepared, prepared / "new-results.jsonl", fake)
    assert fake.calls == []


def test_resume_uses_trial_ids_and_request_indices_not_saved_row_count(prepared, tmp_path):
    output = tmp_path / "results.jsonl"
    execute(prepared, output)
    _, rows = load_run(output)
    _, requests, _ = load_prepared_inputs(prepared)
    # A valid sparse log must skip these specific trials rather than the first two requests.
    save_jsonl(output, [rows[4], rows[1]])
    provider, saved = execute(prepared, output, resume=True)
    assert saved == 6
    assert [request for request, _ in provider.calls] == [
        request for index, request in enumerate(requests) if index not in {1, 4}
    ]
    assert analyze_run(output).complete
    assert len({row.trial_id for row in load_run(output)[1]}) == 8
