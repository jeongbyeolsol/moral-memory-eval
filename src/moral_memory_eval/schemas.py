"""Shared research schemas and versioned metadata, independent of API adapters."""

import hashlib
import random
from typing import Annotated, Literal

from pydantic import Field, model_validator

from llmkit import ClientConfig, GenerationConfig, LLMRequest, LLMResponse
from llmkit.errors import StructuredOutputError
from llmkit.schemas import SchemaModel
from moral_memory_eval._storage import canonical_hash

Text = Annotated[str, Field(min_length=1, pattern=r"\S")]
SHA256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class Profile(SchemaModel):
    id: Text
    memory: Text | None
    candidate_score: Annotated[int, Field(ge=0, le=5)] | None


class Profiles(SchemaModel):
    profiles: Annotated[list[Profile], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_ids(self) -> "Profiles":
        ids = [profile.id for profile in self.profiles]
        if len(ids) != len(set(ids)):
            raise ValueError("Profile IDs must be unique")
        return self


class Claim(SchemaModel):
    id: Text
    sentence: Text
    expected: bool
    dataset: Text
    split: Text


class Verdict(SchemaModel):
    is_true: bool
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)


class SelectionMetadata(SchemaModel):
    path_base: Literal["artifact"] | None = None
    dataset: Literal["CREAK"]
    split: Text
    source_path: Text
    source_sha256: SHA256
    seed: int
    n_true: int = Field(ge=0)
    n_false: int = Field(ge=0)
    selected_ids: Annotated[list[Text], Field(min_length=1)]
    selected_sha256: SHA256
    excluded_ids: list[Text]

    @model_validator(mode="after")
    def validate_counts(self) -> "SelectionMetadata":
        if self.n_true + self.n_false != len(self.selected_ids):
            raise ValueError("Selected ID count must match n_true + n_false")
        if len(set(self.selected_ids)) != len(self.selected_ids):
            raise ValueError("Selected IDs must be unique")
        if len(set(self.excluded_ids)) != len(self.excluded_ids):
            raise ValueError("Excluded IDs must be unique")
        if set(self.selected_ids) & set(self.excluded_ids):
            raise ValueError("Selected and excluded IDs must not overlap")
        return self


class ManifestEntry(SchemaModel):
    trial_id: SHA256
    claim_id: Text
    profile_id: Text
    expected: bool
    repeat_index: int = Field(ge=0)
    prompt_version: Text
    request_index: int = Field(ge=0)
    request_sha256: SHA256


class PreparationSettings(SchemaModel):
    prompt_version: Text
    repeats: int = Field(gt=0)
    seed: int | None
    generation: GenerationConfig
    profiles: Profiles
    claims: Annotated[list[Claim], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_claims(self) -> "PreparationSettings":
        ids = [claim.id for claim in self.claims]
        if len(ids) != len(set(ids)):
            raise ValueError("Claim IDs must be unique")
        return self


class PreparationMetadata(SchemaModel):
    path_base: Literal["artifact"] | None = None
    settings: PreparationSettings
    preparation_sha256: SHA256
    selection_path: Text
    selection_sha256: SHA256
    profiles_path: Text
    profiles_sha256: SHA256
    case_count: int = Field(gt=0)
    requests_sha256: SHA256
    manifest_sha256: SHA256


class PreparedResult(ManifestEntry):
    """Manifest fields remain intact; API results never add researcher data to messages."""

    run_id: Text
    preparation_sha256: SHA256
    request: LLMRequest
    response: LLMResponse
    verdict: Verdict
    client_config: ClientConfig

    @model_validator(mode="after")
    def validate_result(self) -> "PreparedResult":
        if canonical_hash(self.request) != self.request_sha256:
            raise ValueError("Stored request does not match its SHA-256")
        if self.response.provider != self.client_config.provider:
            raise ValueError("Response provider must match client_config")
        try:
            parsed = self.response.parse(Verdict)
        except StructuredOutputError as exc:
            raise ValueError("Response must contain a valid Verdict") from exc
        if parsed != self.verdict:
            raise ValueError("Verdict must match the stored response")
        return self


class PreparedRun(SchemaModel):
    """Saved once per run: the complete planned trial set and immutable model settings."""

    run_id: Text
    preparation: PreparationMetadata
    manifest: Annotated[list[ManifestEntry], Field(min_length=1)]
    client_config: ClientConfig

    @model_validator(mode="after")
    def validate_plan(self) -> "PreparedRun":
        validate_manifest(self.preparation, self.manifest)
        return self


def validate_manifest(preparation: PreparationMetadata, entries: list[ManifestEntry]) -> None:
    """Check the full trial set and order without generating any prompt strings."""
    settings = preparation.settings
    fingerprint = canonical_hash(settings)
    if fingerprint != preparation.preparation_sha256:
        raise ValueError("Preparation settings SHA-256 mismatch")
    conditions = [
        (claim.id, profile.id, repeat_index)
        for claim in settings.claims
        for profile in settings.profiles.profiles
        for repeat_index in range(settings.repeats)
    ]
    if settings.seed is not None:
        random.Random(settings.seed).shuffle(conditions)
    if len(conditions) != preparation.case_count or len(entries) != len(conditions):
        raise ValueError("Planned trial count does not match preparation settings")
    claims = {claim.id: claim for claim in settings.claims}
    for index, entry in enumerate(entries):
        expected_id = hashlib.sha256(f"{fingerprint}:{index}".encode("ascii")).hexdigest()
        if entry.request_index != index or entry.trial_id != expected_id:
            raise ValueError("Manifest trial ID or request index does not match the plan")
        if (
            (entry.claim_id, entry.profile_id, entry.repeat_index) != conditions[index]
            or entry.expected != claims[entry.claim_id].expected
            or entry.prompt_version != settings.prompt_version
        ):
            raise ValueError("Manifest conditions or order do not match preparation settings")


class Metrics(SchemaModel):
    count: int = Field(gt=0)
    false_claim_count: int = Field(ge=0)
    accuracy: float = Field(ge=0, le=1)
    agreement_rate: float = Field(ge=0, le=1)
    false_claim_agreement_rate: float | None = Field(ge=0, le=1)
    mean_confidence: float = Field(ge=0, le=1)
    brier_score: float = Field(ge=0, le=1)


class PreparedAnalysis(SchemaModel):
    run_id: Text
    preparation_sha256: SHA256
    planned_trials: int = Field(gt=0)
    observed_trials: int = Field(ge=0)
    complete: bool
    completed_trial_ids: list[SHA256]
    pending_trial_ids: list[SHA256]
    overall: Metrics | None
    by_profile: dict[str, Metrics]
