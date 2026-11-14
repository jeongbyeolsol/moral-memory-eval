"""Validated input loading and cross-record checks at the experiment boundary."""

from pathlib import Path

from experiments.moral_memory.schemas import Claim, Profiles
from llmkit.io import load_json, load_jsonl
from moral_memory_eval.creak import validate_claims as validate_claims


def load_inputs(profiles_path: Path, claims_path: Path) -> tuple[Profiles, list[Claim]]:
    profiles = load_json(profiles_path, Profiles)
    claims = load_jsonl(claims_path, Claim)
    validate_claims(claims)
    return profiles, claims
