import pytest
from pydantic import ValidationError

from experiments.epistemics.analyze import analyze
from experiments.epistemics.run import DATA_DIR, run_experiment
from experiments.epistemics.schemas import Claim, ExperimentResult, Profile, Profiles
from llmkit import ClientConfig, DataError, LLMClient, LLMResponse, ProviderError
from llmkit.io import load_json, load_jsonl


class ExperimentProvider:
    def __init__(self, fail_after=None):
        self.count = 0
        self.fail_after = fail_after

    def generate(self, request, *, response_model=None):
        if self.fail_after == self.count:
            raise ProviderError("openai", status_code=429)
        self.count += 1
        return LLMResponse(
            provider="openai", model="test", text='{"is_true":true,"reasoning":"test"}'
        )

    def close(self):
        pass


def make_client(provider):
    return LLMClient(ClientConfig(provider="openai", model="test"), provider=provider)


def test_sample_experiment_end_to_end(tmp_path):
    profiles = load_json(DATA_DIR / "profiles.json", Profiles)
    claims = load_jsonl(DATA_DIR / "claims.jsonl", Claim)
    output = tmp_path / "results.jsonl"
    provider = ExperimentProvider()
    with make_client(provider) as client:
        assert run_experiment(client, profiles, claims, output) == 4
    results = load_jsonl(output, ExperimentResult)
    assert len({result.run_id for result in results}) == 1
    assert len({(r.profile.id, r.claim.id) for r in results}) == 4
    summary = analyze(results)
    assert summary.total == 4
    assert all(score.accuracy == 0.5 for score in summary.scores)
    assert all(score.count == 2 for score in summary.scores)


def test_failure_preserves_completed_results(tmp_path):
    output = tmp_path / "results.jsonl"
    with make_client(ExperimentProvider(fail_after=1)) as client:
        with pytest.raises(ProviderError):
            run_experiment(
                client,
                load_json(DATA_DIR / "profiles.json", Profiles),
                load_jsonl(DATA_DIR / "claims.jsonl", Claim),
                output,
            )
    assert len(load_jsonl(output, ExperimentResult)) == 1


def test_existing_output_and_duplicate_ids_fail_before_api(tmp_path):
    profiles = load_json(DATA_DIR / "profiles.json", Profiles)
    claim = Claim(id="x", text="claim", expected=True)
    output = tmp_path / "results.jsonl"
    provider = ExperimentProvider()
    with make_client(provider) as client:
        with pytest.raises(DataError, match="unique"):
            run_experiment(client, profiles, [claim, claim], output)
        assert not output.exists()
        with pytest.raises(DataError, match="At least one"):
            run_experiment(client, profiles, [], output)
        output.write_text("existing")
        with pytest.raises(FileExistsError):
            run_experiment(client, profiles, [claim], output)
    assert provider.count == 0
    assert output.read_text() == "existing"


def test_duplicate_profile_ids_are_rejected():
    profile = Profile(id="x", instruction="test")
    with pytest.raises(ValidationError, match="unique"):
        Profiles(profiles=[profile, profile])


def test_empty_analysis():
    assert analyze([]).total == 0
