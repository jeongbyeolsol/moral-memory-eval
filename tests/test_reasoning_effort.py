import hashlib
import json
import sys

import pytest
from pydantic import ValidationError

from llmkit import (
    ClientConfig,
    ConfigurationError,
    DataError,
    GenerationConfig,
    LLMClient,
    LLMRequest,
)
from llmkit.io import load_json, load_jsonl, save_json
from moral_memory_eval import cli
from moral_memory_eval._storage import canonical_hash
from moral_memory_eval.execution import (
    load_prepared_inputs,
    load_run,
    run_metadata_path,
    run_prepared,
)
from moral_memory_eval.preparation import prepare_requests
from moral_memory_eval.sampling import sample_and_save
from moral_memory_eval.schemas import ManifestEntry, PreparationMetadata, Profile, Profiles


class RecordingProvider:
    def __init__(self):
        self.calls = []

    def generate(self, request, *, response_model=None):
        from llmkit import LLMResponse

        self.calls.append(request)
        return LLMResponse(
            provider="openai", model="mock", text='{"is_true":false,"confidence":0.9}'
        )

    def close(self):
        pass


@pytest.fixture
def files(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    source = raw / "dev.jsonl"
    source.write_text('{"ex_id":"one","sentence":"A sentence.","label":"false"}\n')
    selection = tmp_path / "selected" / "claims.jsonl"
    sample_and_save(source, selection, n_true=0, n_false=1, seed=42)
    profiles = tmp_path / "profiles.json"
    save_json(
        profiles,
        Profiles(
            profiles=[
                Profile(id="no_profile", memory=None, candidate_score=None),
            ]
        ),
    )
    return selection, profiles


@pytest.mark.parametrize("value", ["minimal", "MEDIUM", "", "unknown", 1, False, {}])
def test_bad_reasoning_effort_is_rejected(value):
    with pytest.raises(ValidationError):
        GenerationConfig(reasoning_effort=value)


@pytest.mark.parametrize("explicit_null", [False, True])
def test_legacy_request_serialization_and_hash_unchanged(tmp_path, explicit_null):
    original = {
        "messages": [{"role": "user", "content": "legacy request"}],
        "generation": {"temperature": None, "max_output_tokens": 256},
    }
    incoming = json.loads(json.dumps(original))
    if explicit_null:
        incoming["generation"]["reasoning_effort"] = None
    request = LLMRequest.model_validate(incoming)
    expected_hash = hashlib.sha256(
        json.dumps(
            original,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    assert request.generation.reasoning_effort is None
    assert request.model_dump() == original
    assert json.loads(request.model_dump_json()) == original
    assert canonical_hash(request) == expected_hash
    target = tmp_path / "request.json"
    save_json(target, request)
    assert json.loads(target.read_text())["data"] == original
    assert load_json(target, LLMRequest) == request
    assert GenerationConfig().model_dump() == {"temperature": None, "max_output_tokens": None}


def test_legacy_preparation_settings_hash_and_trial_ids_unchanged(files, tmp_path):
    selection, profiles = files
    directory = tmp_path / "legacy"
    prepare_requests(selection, profiles, ["no_profile"], directory)
    raw_meta = json.loads((directory / "preparation.json").read_text())["data"]
    assert "reasoning_effort" not in raw_meta["settings"]["generation"]
    old_settings_hash = hashlib.sha256(
        json.dumps(
            raw_meta["settings"],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    metadata, requests, manifest = load_prepared_inputs(directory)
    assert canonical_hash(metadata.settings) == old_settings_hash == raw_meta["preparation_sha256"]
    assert manifest[0].trial_id == hashlib.sha256(f"{old_settings_hash}:0".encode()).hexdigest()
    assert "reasoning_effort" not in requests[0].model_dump()["generation"]


def test_reasoning_is_frozen_recorded_executed_and_resume_checked(files, tmp_path):
    selection, profiles = files
    directory = tmp_path / "medium"
    meta = prepare_requests(
        selection,
        profiles,
        ["no_profile"],
        directory,
        repeats=2,
        generation=GenerationConfig(max_output_tokens=1024, reasoning_effort="medium"),
    )
    assert meta.settings.generation.reasoning_effort == "medium"
    assert (
        json.loads((directory / "preparation.json").read_text())["data"]["settings"]["generation"][
            "reasoning_effort"
        ]
        == "medium"
    )
    assert all(
        json.loads(line)["data"]["generation"]["reasoning_effort"] == "medium"
        for line in (directory / "requests.jsonl").read_text().splitlines()
    )
    output = tmp_path / "results.jsonl"
    provider = RecordingProvider()
    config = ClientConfig(provider="openai", model="gpt-6-luna", max_retries=0)
    with LLMClient(config, provider=provider) as client:
        assert run_prepared(client, directory, output, max_calls=1) == 1
    run, rows = load_run(output)
    assert rows[0].request.generation.reasoning_effort == "medium"
    assert run.preparation.settings.generation.reasoning_effort == "medium"
    changed = tmp_path / "high"
    prepare_requests(
        selection,
        profiles,
        ["no_profile"],
        changed,
        repeats=2,
        generation=GenerationConfig(max_output_tokens=1024, reasoning_effort="high"),
    )
    before = output.read_bytes()
    with LLMClient(config, provider=provider) as client:
        with pytest.raises(DataError, match="does not match"):
            run_prepared(client, changed, output, resume=True)
        assert output.read_bytes() == before
        assert len(provider.calls) == 1
        assert run_prepared(client, directory, output, resume=True) == 1
    assert len(provider.calls) == 2
    assert all(request.generation.reasoning_effort == "medium" for request in provider.calls)


def test_gemini_batch_rejected_before_results_created(files, tmp_path):
    selection, profiles = files
    directory = tmp_path / "medium"
    prepare_requests(
        selection,
        profiles,
        ["no_profile"],
        directory,
        generation=GenerationConfig(reasoning_effort="medium"),
    )
    provider = RecordingProvider()
    output = tmp_path / "results.jsonl"
    with LLMClient(ClientConfig(provider="gemini", model="mock"), provider=provider) as client:
        with pytest.raises(ConfigurationError, match="does not support reasoning_effort"):
            run_prepared(client, directory, output)
    assert provider.calls == []
    assert not output.exists() and not run_metadata_path(output).exists()


def test_generic_client_rejects_gemini_effort_before_provider(files):
    from llmkit import Message

    provider = RecordingProvider()
    request = LLMRequest(
        messages=[Message(role="user", content="question")],
        generation=GenerationConfig(reasoning_effort="none"),
    )
    with LLMClient(ClientConfig(provider="gemini", model="mock"), provider=provider) as client:
        with pytest.raises(ConfigurationError, match="reasoning_effort"):
            client.generate(request)
    assert provider.calls == []


@pytest.mark.parametrize("effort", ["none", "low", "medium", "high", "xhigh", "max"])
def test_prepare_cli_effort_choices_and_persistence(files, tmp_path, monkeypatch, effort):
    selection, profiles = files
    directory = tmp_path / effort
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "cli",
            "prepare",
            "--claims",
            str(selection),
            "--profiles",
            str(profiles),
            "--profile-ids",
            "no_profile",
            "--reasoning-effort",
            effort,
            "--output-dir",
            str(directory),
        ],
    )
    cli.main()
    assert (
        load_json(
            directory / "preparation.json", PreparationMetadata
        ).settings.generation.reasoning_effort
        == effort
    )
    assert (
        load_jsonl(directory / "requests.jsonl", LLMRequest)[0].generation.reasoning_effort
        == effort
    )
    assert len(load_jsonl(directory / "manifest.jsonl", ManifestEntry)) == 1


def test_prepare_cli_rejects_bad_effort_without_writes(files, tmp_path, monkeypatch):
    selection, profiles = files
    directory = tmp_path / "invalid"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "cli",
            "prepare",
            "--claims",
            str(selection),
            "--profiles",
            str(profiles),
            "--profile-ids",
            "no_profile",
            "--reasoning-effort",
            "minimal",
            "--output-dir",
            str(directory),
        ],
    )
    with pytest.raises(SystemExit) as caught:
        cli.main()
    assert caught.value.code == 2
    assert not directory.exists()


def test_prepare_cli_omitted_effort_preserves_legacy_generation_shape(files, tmp_path, monkeypatch):
    selection, profiles = files
    directory = tmp_path / "omitted"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "cli",
            "prepare",
            "--claims",
            str(selection),
            "--profiles",
            str(profiles),
            "--profile-ids",
            "no_profile",
            "--output-dir",
            str(directory),
        ],
    )
    cli.main()
    raw_settings = json.loads((directory / "preparation.json").read_text())["data"]["settings"]
    assert raw_settings["generation"] == {"temperature": None, "max_output_tokens": 1024}
    metadata, requests, _ = load_prepared_inputs(directory)
    assert metadata.settings.generation.reasoning_effort is None
    assert requests[0].generation.reasoning_effort is None
