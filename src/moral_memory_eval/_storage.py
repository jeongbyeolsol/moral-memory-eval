"""Small storage primitives: hashes, exclusive publication, and raw-data protection."""

import hashlib
import json
import os
from pathlib import Path

from pydantic import BaseModel

from llmkit import DataError


def sha256_file(path: Path) -> str:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError as exc:
        raise DataError(f"{path}: unable to calculate SHA-256") from exc


def canonical_hash(value: BaseModel) -> str:
    payload = json.dumps(
        value.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def protect_source_tree(source: Path, destination: Path) -> None:
    if destination.resolve().is_relative_to(source.resolve().parent):
        raise DataError(f"Refusing to write inside the raw source directory: {destination}")


def require_new(path: Path) -> None:
    if os.path.lexists(path):
        raise DataError(f"Output already exists; choose a new path: {path}")


def publish_files(pairs: list[tuple[Path, Path]]) -> None:
    """Link staged files exclusively; publish metadata last as the commit marker.

    A failure rolls back only the links created here, never pre-existing files.
    Staging under the destination parent keeps links on the same filesystem.
    """
    published: list[tuple[Path, Path]] = []
    try:
        for staged, destination in pairs:
            os.link(staged, destination)
            published.append((staged, destination))
    except OSError as exc:
        for staged, destination in reversed(published):
            if destination.exists() and os.path.samestat(staged.stat(), destination.stat()):
                destination.unlink()
        raise DataError(f"Unable to publish selected data without overwriting: {exc}") from exc


def publish_directory(staged: Path, destination: Path) -> None:
    """Reserve a new name, then replace that empty reservation with the validated tree."""
    reserved = False
    try:
        destination.mkdir()  # exclusive, including against an empty existing directory
        reserved = True
        os.replace(staged, destination)
    except OSError as exc:
        if reserved:
            destination.rmdir()  # only our own, still-empty reservation
        raise DataError(f"Unable to publish prepared directory: {destination}: {exc}") from exc
