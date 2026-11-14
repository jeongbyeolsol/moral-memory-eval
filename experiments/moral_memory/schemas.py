"""Experiment-owned contracts; llmkit's provider-independent models stay unchanged."""

from pydantic import Field, model_validator

from llmkit import ClientConfig, GenerationConfig, LLMRequest, LLMResponse
from llmkit.errors import StructuredOutputError
from llmkit.schemas import SchemaModel
from moral_memory_eval.schemas import Claim as Claim
from moral_memory_eval.schemas import Profile as Profile
from moral_memory_eval.schemas import Profiles as Profiles
from moral_memory_eval.schemas import Text as Text
from moral_memory_eval.schemas import Verdict as Verdict


class RunConfig(SchemaModel):
    repeats: int = Field(default=1, gt=0)
    seed: int | None = None
    generation: GenerationConfig = Field(default_factory=GenerationConfig)


class ExperimentResult(SchemaModel):
    run_id: Text
    trial_id: Text
    repeat_index: int = Field(ge=0)
    prompt_version: Text
    planned_trials: int = Field(gt=0)
    profile: Profile
    claim: Claim
    request: LLMRequest
    response: LLMResponse
    verdict: Verdict
    # Preserve settings for provenance; neither object contains credentials.
    run_config: RunConfig
    client_config: ClientConfig

    @model_validator(mode="after")
    def validate_result(self) -> "ExperimentResult":
        if self.repeat_index >= self.run_config.repeats:
            raise ValueError("repeat_index must be smaller than repeats")
        if self.response.provider != self.client_config.provider:
            raise ValueError("response provider must match client_config")
        if self.request.generation != self.run_config.generation:
            raise ValueError("request generation must match run_config")
        try:
            verdict = self.response.parse(Verdict)
        except StructuredOutputError as exc:
            raise ValueError("response must contain a valid Verdict") from exc
        if verdict != self.verdict:
            raise ValueError("verdict must match the stored response")
        return self


class Metrics(SchemaModel):
    count: int = Field(gt=0)
    false_claim_count: int = Field(ge=0)
    accuracy: float = Field(ge=0, le=1)
    agreement_rate: float = Field(ge=0, le=1)
    false_claim_agreement_rate: float | None = Field(ge=0, le=1)
    mean_confidence: float = Field(ge=0, le=1)
    brier_score: float = Field(ge=0, le=1)


class Analysis(SchemaModel):
    run_id: Text
    prompt_version: Text
    planned_trials: int = Field(gt=0)
    observed_trials: int = Field(gt=0)
    complete: bool
    overall: Metrics
    by_profile: dict[str, Metrics]
