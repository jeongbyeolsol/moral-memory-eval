"""Execute frozen requests, persist manifest-linked results, and resume validated runs."""

import fcntl
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from llmkit import ClientConfig, DataError, LLMClient, LLMKitError, LLMRequest
from llmkit.config import ensure_generation_supported
from llmkit.io import append_jsonl, load_json, load_jsonl, save_json, save_jsonl
from moral_memory_eval._storage import (
    canonical_hash,
    publish_files,
    require_new,
    resolve_reference,
    sha256_file,
)
from moral_memory_eval.preparation import validate_prepared_records, verify_prepared
from moral_memory_eval.schemas import (
    ManifestEntry,
    PreparationMetadata,
    PreparedResult,
    PreparedRun,
    Verdict,
)


class ExecutionError(LLMKitError):
    """A failed trial; the original provider/validation/storage error is chained."""


def run_metadata_path(output: Path) -> Path:
    return output.with_suffix(".run.json")


def load_prepared_inputs(
    directory: Path,
) -> tuple[PreparationMetadata, list[LLMRequest], list[ManifestEntry]]:
    metadata = verify_prepared(directory, verify_prompts=False)
    requests = load_jsonl(directory / "requests.jsonl", LLMRequest)
    entries = load_jsonl(directory / "manifest.jsonl", ManifestEntry)
    validate_prepared_records(metadata, requests, entries)
    # Also detect changes between the initial verification and this in-memory snapshot.
    if (
        sha256_file(directory / "requests.jsonl") != metadata.requests_sha256
        or sha256_file(directory / "manifest.jsonl") != metadata.manifest_sha256
    ):
        raise DataError("Prepared input files changed while loading")
    return metadata, requests, entries


def validate_completed(run: PreparedRun, results: list[PreparedResult]) -> set[str]:
    planned = {entry.trial_id: entry for entry in run.manifest}
    completed: set[str] = set()
    for row in results:
        entry = planned.get(row.trial_id)
        if entry is None:
            raise DataError(f"Unplanned trial_id: {row.trial_id}")
        if row.trial_id in completed:
            raise DataError(f"Duplicate completed trial_id: {row.trial_id}")
        stored_entry = ManifestEntry.model_validate(
            row.model_dump(include=set(ManifestEntry.model_fields))
        )
        if (
            stored_entry != entry
            or row.run_id != run.run_id
            or row.preparation_sha256 != run.preparation.preparation_sha256
            or row.client_config != run.client_config
            or canonical_hash(row.request) != entry.request_sha256
            or row.request.generation != run.preparation.settings.generation
        ):
            raise DataError(f"Completed result does not match the saved run: {row.trial_id}")
        completed.add(row.trial_id)
    return completed


def load_run(output: Path) -> tuple[PreparedRun, list[PreparedResult]]:
    run = load_json(run_metadata_path(output), PreparedRun)
    results = load_jsonl(output, PreparedResult)
    validate_completed(run, results)
    return run, results


def _match_preparation(
    run: PreparedRun,
    metadata: PreparationMetadata,
    entries: list[ManifestEntry],
) -> None:
    # Paths are provenance, not identity: an identical prepared bundle may be moved.
    if (
        run.preparation.settings != metadata.settings
        or run.preparation.preparation_sha256 != metadata.preparation_sha256
        or run.preparation.requests_sha256 != metadata.requests_sha256
        or run.preparation.manifest_sha256 != metadata.manifest_sha256
        or run.manifest != entries
    ):
        raise DataError("Existing run does not match the prepared input bundle")


def preview_run(input_dir: Path, output: Path, *, resume: bool = False) -> tuple[int, int]:
    metadata, _, entries = load_prepared_inputs(input_dir)
    if resume:
        run, results = load_run(output)
        _match_preparation(run, metadata, entries)
        return metadata.case_count, len(results)
    require_new(output)
    require_new(run_metadata_path(output))
    return metadata.case_count, 0


@contextmanager
def _result_lock(output: Path) -> Iterator[None]:
    """One writer per result file. Keep the lock inode to avoid concurrent-resume races."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.with_suffix(output.suffix + ".lock").open("a", encoding="utf-8") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise DataError(f"Another process is using the result file: {output}") from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def _new_run(
    output: Path,
    metadata: PreparationMetadata,
    entries: list[ManifestEntry],
    config: ClientConfig,
) -> PreparedRun:
    require_new(output)
    require_new(run_metadata_path(output))
    run = PreparedRun(
        run_id=str(uuid4()),
        preparation=metadata,
        manifest=entries,
        client_config=config,
    )
    with tempfile.TemporaryDirectory(prefix=".run-", dir=output.parent) as folder:
        staged = Path(folder)
        save_jsonl(staged / "results.jsonl", [])
        save_json(staged / "run.json", run)
        publish_files(
            [
                (staged / "results.jsonl", output),
                (staged / "run.json", run_metadata_path(output)),
            ]
        )
    return run


def run_prepared(
    client: LLMClient,
    input_dir: Path,
    output: Path,
    *,
    resume: bool = False,
    max_calls: int | None = None,
) -> int:
    """Return newly saved successes; preserve prepared order and never rebuild prompts."""
    if max_calls is not None and (type(max_calls) is not int or max_calls <= 0):
        raise DataError("max_calls must be a positive integer")
    if output.suffix != ".jsonl":
        raise DataError("Result output must have a .jsonl extension")
    metadata, requests, entries = load_prepared_inputs(input_dir)
    # Validate the whole batch before any calls, locks, or result publication.
    for request in requests:
        ensure_generation_supported(client.config.provider, request.generation)
    if output.resolve().is_relative_to(input_dir.resolve()) or output.resolve().is_relative_to(
        resolve_reference(metadata.selection_path, input_dir, metadata.path_base).resolve().parent
    ):
        raise DataError("Results must be outside prepared inputs and selected data directories")
    with _result_lock(output):
        if resume:
            run, results = load_run(output)
            _match_preparation(run, metadata, entries)
            if run.client_config != client.config:
                raise DataError(
                    "Resume requires the original provider, model, timeout, and retries"
                )
            completed = validate_completed(run, results)
        else:
            run = _new_run(output, metadata, entries, client.config)
            completed = set()
        newly_saved = 0
        for entry in entries:
            if entry.trial_id in completed:
                continue
            if max_calls is not None and newly_saved >= max_calls:
                break
            request = requests[entry.request_index]
            try:
                response = client.generate(request, response_model=Verdict)
                result = PreparedResult(
                    **entry.model_dump(),
                    run_id=run.run_id,
                    preparation_sha256=metadata.preparation_sha256,
                    request=request,
                    response=response,
                    verdict=response.parse(Verdict),
                    client_config=client.config,
                )
                append_jsonl(output, result)
            except (LLMKitError, ValidationError, OSError) as exc:
                raise ExecutionError(
                    f"trial_id={entry.trial_id}, request_index={entry.request_index}: "
                    f"{type(exc).__name__}: {exc}; completed={len(completed)}/{len(entries)}"
                ) from exc
            completed.add(entry.trial_id)
            newly_saved += 1
        return newly_saved
