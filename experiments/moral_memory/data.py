"""Validated input loading and cross-record checks at the experiment boundary."""

from pathlib import Path

from experiments.moral_memory.schemas import Claim, Profiles
from llmkit import DataError
from llmkit.io import load_json, load_jsonl


def validate_claims(claims: list[Claim]) -> None:
    if not claims:
        raise DataError("At least one claim is required")
    ids = [claim.id for claim in claims]
    if len(ids) != len(set(ids)):
        raise DataError("Claim IDs must be unique")


def load_inputs(profiles_path: Path, claims_path: Path) -> tuple[Profiles, list[Claim]]:
    profiles = load_json(profiles_path, Profiles)
    claims = load_jsonl(claims_path, Claim)
    validate_claims(claims)
    return profiles, claims
