"""Shared research schemas and versioned metadata, independent of API adapters."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from llmkit import GenerationConfig
from llmkit.schemas import SchemaModel

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
    settings: PreparationSettings
    preparation_sha256: SHA256
    selection_path: Text
    selection_sha256: SHA256
    profiles_path: Text
    profiles_sha256: SHA256
    case_count: int = Field(gt=0)
    requests_sha256: SHA256
    manifest_sha256: SHA256
