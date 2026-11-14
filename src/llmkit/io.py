"""Versioned JSON/JSONL boundaries shared by library and experiment models.

On disk each record is {"schema_version": "1.0", "data": <model payload>}.
Migrations are explicit, caller-owned functions converting a historical envelope
to the current envelope. Unversioned input is deliberately rejected.
"""

import json
import os
import tempfile
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel

from llmkit.errors import DataError
from llmkit.schemas import SchemaModel

T = TypeVar("T", bound=BaseModel)
Migration = Callable[[dict[str, Any]], dict[str, Any]]
SCHEMA_VERSION = "1.0"


class _Record(SchemaModel, Generic[T]):
    schema_version: Literal["1.0"]
    data: T


def _reject_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON number: {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def _decode(
    text: str,
    model: type[T],
    location: str,
    migrations: Mapping[str, Migration] | None,
) -> T:
    try:
        raw = json.loads(text, parse_constant=_reject_constant, object_pairs_hook=_unique_object)
        if not isinstance(raw, dict):
            raise ValueError("Expected a versioned object")
        version = raw.get("schema_version")
        if not isinstance(version, str):
            raise ValueError("schema_version must be an explicit string")
        if version != SCHEMA_VERSION:
            migrate = (migrations or {}).get(version)
            if migrate is None:
                raise ValueError(f"Unsupported schema_version: {version!r}")
            raw = migrate(raw)
        # Validate through JSON to support datetime/tuple fields in strict models.
        record_model: type[_Record[T]] = _Record[model]  # type: ignore[valid-type]
        return record_model.model_validate_json(
            json.dumps(raw, ensure_ascii=False, allow_nan=False), strict=True
        ).data
    except (ValueError, TypeError, KeyError) as exc:
        raise DataError(f"{location}: {exc}") from exc


def load_json(
    path: str | Path, model: type[T], *, migrations: Mapping[str, Migration] | None = None
) -> T:
    source = Path(path)
    try:
        return _decode(source.read_text(encoding="utf-8"), model, str(source), migrations)
    except (OSError, UnicodeError) as exc:
        raise DataError(f"{source}: unable to read UTF-8 JSON") from exc


def load_jsonl(
    path: str | Path, model: type[T], *, migrations: Mapping[str, Migration] | None = None
) -> list[T]:
    """Validate the entire file before returning; errors include the line number."""
    source = Path(path)
    try:
        with source.open(encoding="utf-8") as stream:
            return [
                _decode(line, model, f"{source}:{number}", migrations)
                for number, line in enumerate(stream, start=1)
            ]
    except (OSError, UnicodeError) as exc:
        raise DataError(f"{source}: unable to read UTF-8 JSONL") from exc


def _encode(value: BaseModel) -> str:
    try:
        # Revalidate to catch in-place edits to mutable fields of frozen models.
        validated = type(value).model_validate_json(
            value.model_dump_json(warnings="error"), strict=True
        )
        return json.dumps(
            {"schema_version": SCHEMA_VERSION, "data": validated.model_dump(mode="json")},
            ensure_ascii=False,
            allow_nan=False,
        )
    except (ValueError, TypeError) as exc:
        raise DataError(f"Unable to serialize {type(value).__name__}: {exc}") from exc


def _atomic_write(path: Path, text: str) -> None:
    """Replace only after all records are validated and the new file is written."""
    temporary: str | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as stream:
            temporary = stream.name
            stream.write(text)
        os.replace(temporary, path)
    except OSError as exc:
        raise DataError(f"{path}: unable to write data") from exc
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def save_json(path: str | Path, value: BaseModel) -> None:
    _atomic_write(Path(path), _encode(value) + "\n")


def save_jsonl(path: str | Path, values: Iterable[BaseModel]) -> None:
    _atomic_write(Path(path), "".join(_encode(value) + "\n" for value in values))


def append_jsonl(path: str | Path, value: BaseModel) -> None:
    """Persist one completed result. Intended for a single writer per file."""
    encoded = _encode(value) + "\n"
    destination = Path(path)
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("a", encoding="utf-8") as stream:
            stream.write(encoded)
    except OSError as exc:
        raise DataError(f"{destination}: unable to append JSONL") from exc
