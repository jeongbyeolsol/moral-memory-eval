"""Reproducible label sampling and persistent, hash-checked selection artifacts."""

import random
import tempfile
from pathlib import Path

from pydantic import ValidationError

from llmkit import DataError
from llmkit.io import load_json, save_json, save_jsonl
from moral_memory_eval._storage import (
    protect_source_tree,
    publish_files,
    require_new,
    sha256_file,
)
from moral_memory_eval.creak import load_claims, read_creak_snapshot, validate_claims
from moral_memory_eval.schemas import Claim, SelectionMetadata


def metadata_path(path: Path) -> Path:
    return path.with_suffix(".meta.json")


def sample_claims(
    claims: list[Claim],
    n_true: int,
    n_false: int,
    seed: int,
    exclude_ids: set[str] | None = None,
) -> list[Claim]:
    validate_claims(claims)
    if any(type(count) is not int or count < 0 for count in (n_true, n_false)):
        raise DataError("n_true and n_false must be non-negative integers")
    if n_true + n_false == 0:
        raise DataError("At least one claim must be selected")
    if type(seed) is not int:
        raise DataError("seed must be an integer")
    excluded = exclude_ids if exclude_ids is not None else set()
    rng = random.Random(seed)
    selected = []
    for label, count in ((True, n_true), (False, n_false)):
        candidates = [c for c in claims if c.expected == label and c.id not in excluded]
        if len(candidates) < count:
            raise DataError(f"Need {count} claims for label {label}; found {len(candidates)}")
        selected.extend(rng.sample(candidates, count))
    rng.shuffle(selected)
    return selected


def load_selection(path: Path) -> tuple[list[Claim], SelectionMetadata]:
    """Require both artifacts and check exact stored bytes plus semantic metadata."""
    meta = load_json(metadata_path(path), SelectionMetadata)
    if sha256_file(path) != meta.selected_sha256:
        raise DataError(f"{path}: selected file SHA-256 mismatch")
    claims = load_claims(path)
    if [claim.id for claim in claims] != meta.selected_ids:
        raise DataError(f"{path}: selected ID order does not match metadata")
    if (
        sum(claim.expected for claim in claims) != meta.n_true
        or sum(not claim.expected for claim in claims) != meta.n_false
        or any(claim.dataset != meta.dataset or claim.split != meta.split for claim in claims)
    ):
        raise DataError(f"{path}: label counts, dataset, or split do not match metadata")
    return claims, meta


def verify_disjoint(left: Path, right: Path) -> None:
    a, _ = load_selection(left)
    b, _ = load_selection(right)
    overlap = sorted({claim.id for claim in a} & {claim.id for claim in b})
    if overlap:
        raise DataError(f"Overlapping claim IDs: {overlap}")


def sample_and_save(
    source: Path,
    output: Path,
    *,
    n_true: int,
    n_false: int,
    seed: int,
    split: str = "dev",
    exclude_claims: list[Path] | None = None,
) -> SelectionMetadata:
    protect_source_tree(source, output)
    if output.suffix.lower() != ".jsonl":
        raise DataError("Selected data output must have a .jsonl extension")
    require_new(output)
    require_new(metadata_path(output))
    excluded: set[str] = set()
    for path in exclude_claims or []:
        previous, _ = load_selection(path)
        excluded.update(claim.id for claim in previous)
    claims, source_hash = read_creak_snapshot(source, split)
    selected = sample_claims(claims, n_true, n_false, seed, excluded)
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".sample-", dir=output.parent) as folder:
            staged = Path(folder) / output.name
            save_jsonl(staged, selected)
            meta = SelectionMetadata(
                dataset="CREAK",
                split=split,
                source_path=str(source.resolve()),
                source_sha256=source_hash,
                seed=seed,
                n_true=n_true,
                n_false=n_false,
                selected_ids=[claim.id for claim in selected],
                selected_sha256=sha256_file(staged),
                excluded_ids=sorted(excluded),
            )
            save_json(metadata_path(staged), meta)
            reread, checked = load_selection(staged)
            if reread != selected or checked != meta:
                raise DataError("Staged selection does not match the sampled data")
            publish_files([(staged, output), (metadata_path(staged), metadata_path(output))])
    except (OSError, ValidationError) as exc:
        raise DataError(f"{output}: unable to save selection: {exc}") from exc
    reread, checked = load_selection(output)
    if reread != selected or checked != meta:
        raise DataError(f"{output}: saved selection verification failed")
    return meta
