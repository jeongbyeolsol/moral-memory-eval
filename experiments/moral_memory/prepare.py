"""Convert labeled CREAK JSONL (including .json files) to versioned Claim records."""

import argparse
import random
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from experiments.moral_memory.data import validate_claims
from experiments.moral_memory.schemas import Claim, Text
from llmkit import DataError, LLMKitError
from llmkit.io import save_jsonl


class _CreakRecord(BaseModel):
    # Source metadata (explanation, entity, etc.) is intentionally not imported.
    model_config = ConfigDict(strict=True, extra="ignore")
    ex_id: Text
    sentence: Text
    label: Literal["true", "false"]


def load_creak(path: Path, split: str) -> list[Claim]:
    claims = []
    try:
        with path.open(encoding="utf-8") as stream:
            for number, line in enumerate(stream, start=1):
                # Raw CREAK files may contain blank lines; normalized JSONL may not.
                if not line.strip():
                    continue
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
    except (OSError, UnicodeError) as exc:
        raise DataError(f"{path}: unable to read CREAK data") from exc
    validate_claims(claims)
    return claims


def select_claims(
    claims: list[Claim], *, ids: list[str] | None = None, per_label: int = 15, seed: int = 0
) -> list[Claim]:
    validate_claims(claims)
    if ids is not None:
        if not ids or len(set(ids)) != len(ids):
            raise DataError("Selected IDs must be nonempty and unique")
        by_id = {claim.id: claim for claim in claims}
        missing = [claim_id for claim_id in ids if claim_id not in by_id]
        if missing:
            raise DataError(f"Unknown CREAK IDs: {missing}")
        return [by_id[claim_id] for claim_id in ids]
    if per_label <= 0:
        raise DataError("per_label must be positive")
    rng = random.Random(seed)
    selected = []
    for label in (True, False):
        candidates = [claim for claim in claims if claim.expected == label]
        if len(candidates) < per_label:
            raise DataError(f"Need {per_label} claims for label {label}; found {len(candidates)}")
        selected.extend(rng.sample(candidates, per_label))
    rng.shuffle(selected)
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare labeled CREAK claims without API calls")
    parser.add_argument(
        "source", type=Path, help="Raw labeled CREAK JSONL, even if extension is .json"
    )
    parser.add_argument("--split", required=True)
    parser.add_argument("--output", type=Path, required=True, help="New versioned JSONL file")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--ids", nargs="+", help="Explicit CREAK IDs in desired order")
    selection.add_argument("--per-label", type=int, default=15)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    try:
        claims = select_claims(
            load_creak(args.source, args.split),
            ids=args.ids,
            per_label=args.per_label,
            seed=args.seed,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8"):
            pass
        save_jsonl(args.output, claims)
    except (LLMKitError, OSError) as exc:
        parser.exit(1, f"{type(exc).__name__}: {exc}\n")
    print(f"Saved {len(claims)} claims to {args.output}; review them before the main experiment")


if __name__ == "__main__":
    main()
