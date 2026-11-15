"""Generate API-only requests and separate, reproducible case manifests offline."""

import hashlib
import random
import tempfile
from pathlib import Path

from llmkit import DataError, GenerationConfig, LLMRequest
from llmkit.io import load_json, load_jsonl, save_json, save_jsonl
from moral_memory_eval._storage import (
    canonical_hash,
    protect_source_tree,
    publish_directory,
    relative_reference,
    require_new,
    resolve_reference,
    sha256_file,
)
from moral_memory_eval.prompts import PROMPT_VERSION, build_request
from moral_memory_eval.sampling import load_selection
from moral_memory_eval.schemas import (
    ManifestEntry,
    PreparationMetadata,
    PreparationSettings,
    Profiles,
    validate_manifest,
)


def select_profiles(profiles: Profiles, profile_ids: list[str]) -> Profiles:
    if not profile_ids or len(set(profile_ids)) != len(profile_ids):
        raise DataError("Selected profile IDs must be nonempty and unique")
    by_id = {profile.id: profile for profile in profiles.profiles}
    missing = [profile_id for profile_id in profile_ids if profile_id not in by_id]
    if missing:
        raise DataError(f"Unknown profile IDs: {missing}")
    return Profiles(profiles=[by_id[profile_id] for profile_id in profile_ids])


def build_cases(settings: PreparationSettings) -> tuple[list[LLMRequest], list[ManifestEntry]]:
    if settings.prompt_version != PROMPT_VERSION:
        raise DataError(f"Unsupported prompt version: {settings.prompt_version}")
    combinations = [
        (claim, profile, repeat_index)
        for claim in settings.claims
        for profile in settings.profiles.profiles
        for repeat_index in range(settings.repeats)
    ]
    if settings.seed is not None:
        random.Random(settings.seed).shuffle(combinations)
    fingerprint = canonical_hash(settings)
    requests = []
    entries = []
    for index, (claim, profile, repeat_index) in enumerate(combinations):
        request = build_request(profile, claim, settings.generation)
        requests.append(request)
        entries.append(
            ManifestEntry(
                trial_id=hashlib.sha256(f"{fingerprint}:{index}".encode("ascii")).hexdigest(),
                claim_id=claim.id,
                profile_id=profile.id,
                expected=claim.expected,
                repeat_index=repeat_index,
                prompt_version=settings.prompt_version,
                request_index=index,
                request_sha256=canonical_hash(request),
            )
        )
    return requests, entries


def verify_prepared(directory: Path, *, verify_prompts: bool = True) -> PreparationMetadata:
    """Verify self-contained snapshots, complete combinations, order, and both file hashes."""
    metadata = load_json(directory / "preparation.json", PreparationMetadata)
    if metadata.preparation_sha256 != canonical_hash(metadata.settings):
        raise DataError(f"{directory}: preparation settings SHA-256 mismatch")
    if sha256_file(directory / "requests.jsonl") != metadata.requests_sha256:
        raise DataError(f"{directory}: request file SHA-256 mismatch")
    if sha256_file(directory / "manifest.jsonl") != metadata.manifest_sha256:
        raise DataError(f"{directory}: manifest file SHA-256 mismatch")
    requests = load_jsonl(directory / "requests.jsonl", LLMRequest)
    entries = load_jsonl(directory / "manifest.jsonl", ManifestEntry)
    if len(requests) != len(entries) or len(entries) != metadata.case_count:
        raise DataError(f"{directory}: request/manifest count mismatch")
    validate_prepared_records(metadata, requests, entries, verify_prompts=verify_prompts)
    return metadata


def validate_prepared_records(
    metadata: PreparationMetadata,
    requests: list[LLMRequest],
    entries: list[ManifestEntry],
    *,
    verify_prompts: bool = False,
) -> None:
    """Validate saved correspondence without rebuilding prompts during execution."""
    if len(requests) != len(entries) or len(entries) != metadata.case_count:
        raise DataError("Prepared request/manifest count mismatch")
    try:
        validate_manifest(metadata, entries)
    except ValueError as exc:
        raise DataError(
            f"Prepared request/manifest content or order does not match settings: {exc}"
        ) from exc
    for index, entry in enumerate(entries):
        request = requests[entry.request_index]
        if (
            entry.request_index != index
            or canonical_hash(request) != entry.request_sha256
            or request.generation != metadata.settings.generation
        ):
            raise DataError("Prepared request hash, index, or generation does not match manifest")
    if verify_prompts:
        expected_requests, expected_entries = build_cases(metadata.settings)
        if requests != expected_requests or entries != expected_entries:
            raise DataError("Prepared request/manifest content or order does not match settings")


def prepare_requests(
    claims_path: Path,
    profiles_path: Path,
    profile_ids: list[str],
    output_dir: Path,
    *,
    repeats: int = 1,
    seed: int | None = None,
    generation: GenerationConfig | None = None,
) -> PreparationMetadata:
    """Read frozen selections only; no raw-source read, sampling, dotenv, or API use."""
    require_new(output_dir)
    claims, selection = load_selection(claims_path)
    source = resolve_reference(selection.source_path, claims_path.parent, selection.path_base)
    protect_source_tree(source, output_dir)
    profile_hash = sha256_file(profiles_path)
    profiles = select_profiles(load_json(profiles_path, Profiles), profile_ids)
    if profile_hash != sha256_file(profiles_path):
        raise DataError("Profile file changed during preparation")
    settings = PreparationSettings(
        prompt_version=PROMPT_VERSION,
        repeats=repeats,
        seed=seed,
        generation=(
            generation if generation is not None else GenerationConfig(max_output_tokens=256)
        ),
        profiles=profiles,
        claims=claims,
    )
    requests, entries = build_cases(settings)
    try:
        output_dir.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".prepare-", dir=output_dir.parent) as folder:
            staged = Path(folder)
            save_jsonl(staged / "requests.jsonl", requests)
            save_jsonl(staged / "manifest.jsonl", entries)
            metadata = PreparationMetadata(
                path_base="artifact",
                settings=settings,
                preparation_sha256=canonical_hash(settings),
                selection_path=relative_reference(claims_path, output_dir),
                selection_sha256=selection.selected_sha256,
                profiles_path=relative_reference(profiles_path, output_dir),
                profiles_sha256=profile_hash,
                case_count=len(requests),
                requests_sha256=sha256_file(staged / "requests.jsonl"),
                manifest_sha256=sha256_file(staged / "manifest.jsonl"),
            )
            save_json(staged / "preparation.json", metadata)
            verify_prepared(staged)
            publish_directory(staged, output_dir)
    except OSError as exc:
        raise DataError(f"{output_dir}: unable to prepare requests: {exc}") from exc
    return verify_prepared(output_dir)
