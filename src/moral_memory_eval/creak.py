"""Read-only raw CREAK JSONL conversion; normalized claims use llmkit.io."""

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from llmkit import DataError
from llmkit.io import load_jsonl
from moral_memory_eval.schemas import Claim, Text


class _CreakRecord(BaseModel):
    # Preserve the source unchanged; explanation/entity are not part of model input.
    model_config = ConfigDict(strict=True, extra="ignore")
    ex_id: Text
    sentence: Text
    label: Literal["true", "false"]


def validate_claims(claims: list[Claim]) -> None:
    if not claims:
        raise DataError("At least one claim is required")
    ids = [claim.id for claim in claims]
    if len(ids) != len(set(ids)):
        raise DataError("Claim IDs must be unique")


def read_creak_snapshot(path: Path, split: str) -> tuple[list[Claim], str]:
    """Parse and hash the same source bytes so provenance cannot race a second read."""
    try:
        content = path.read_bytes()
        text = content.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise DataError(f"{path}: unable to read CREAK data") from exc
    claims = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue  # blank lines occur in the raw release, not in normalized JSONL
        try:
            record = _CreakRecord.model_validate_json(line, strict=True)
            claims.append(
                Claim(
                    id=record.ex_id,
                    sentence=record.sentence,
                    expected=record.label == "true",
                    dataset="CREAK",
                    split=split,
                )
            )
        except ValidationError as exc:
            raise DataError(f"{path}:{number}: {exc}") from exc
    validate_claims(claims)
    return claims, hashlib.sha256(content).hexdigest()


def load_creak(path: Path, split: str) -> list[Claim]:
    return read_creak_snapshot(path, split)[0]


def load_claims(path: Path) -> list[Claim]:
    claims = load_jsonl(path, Claim)
    validate_claims(claims)
    return claims
