"""Experiment-specific data contracts, independent of provider SDKs."""

from typing import Annotated

from pydantic import Field, model_validator

from llmkit import LLMRequest, LLMResponse
from llmkit.errors import StructuredOutputError
from llmkit.schemas import NonEmptyString, SchemaModel


class Profile(SchemaModel):
    id: NonEmptyString
    instruction: NonEmptyString


class Profiles(SchemaModel):
    profiles: Annotated[list[Profile], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_ids(self) -> "Profiles":
        ids = [profile.id for profile in self.profiles]
        if len(ids) != len(set(ids)):
            raise ValueError("Profile IDs must be unique")
        return self


class Claim(SchemaModel):
    id: NonEmptyString
    text: NonEmptyString
    expected: bool


class Verdict(SchemaModel):
    is_true: bool
    reasoning: NonEmptyString


class ExperimentResult(SchemaModel):
    run_id: NonEmptyString
    profile: Profile
    claim: Claim
    request: LLMRequest
    response: LLMResponse
    verdict: Verdict

    @model_validator(mode="after")
    def consistent_verdict(self) -> "ExperimentResult":
        try:
            parsed = self.response.parse(Verdict)
        except StructuredOutputError as exc:
            raise ValueError("response must contain a valid verdict") from exc
        if parsed != self.verdict:
            raise ValueError("verdict must match the stored response")
        return self


class ProfileScore(SchemaModel):
    profile_id: NonEmptyString
    count: int = Field(gt=0)
    correct: int = Field(ge=0)
    accuracy: float = Field(ge=0, le=1)


class Analysis(SchemaModel):
    total: int = Field(ge=0)
    scores: list[ProfileScore]
