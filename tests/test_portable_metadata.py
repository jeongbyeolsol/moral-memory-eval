import shutil
from pathlib import Path

import pytest

from llmkit import ClientConfig, DataError, LLMClient, LLMResponse
from llmkit.io import save_json
from moral_memory_eval._storage import resolve_reference
from moral_memory_eval.execution import run_prepared
from moral_memory_eval.preparation import prepare_requests, verify_prepared
from moral_memory_eval.sampling import load_selection, metadata_path, sample_and_save
from moral_memory_eval.schemas import Profile, Profiles


class FakeProvider:
    def generate(self, request, *, response_model=None):
        return LLMResponse(
            provider="openai", model="mock", text='{"is_true":false,"confidence":0.8}'
        )

    def close(self):
        pass


@pytest.fixture
def project(tmp_path):
    original = tmp_path / "original"
    external = tmp_path / "external-raw"
    external.mkdir()
    source = external / "dev.jsonl"
    source.write_text('{"ex_id":"one","sentence":"A statement.","label":"false"}\n')
    dataset = original / "dataset"
    dataset.mkdir(parents=True)
    (dataset / "creak").symlink_to(external, target_is_directory=True)
    selected = dataset / "selected_data" / "set" / "claims.jsonl"
    sample_and_save(dataset / "creak" / "dev.jsonl", selected, n_true=0, n_false=1, seed=42)
    profile_path = original / "configs" / "profiles.json"
    save_json(
        profile_path,
        Profiles(
            profiles=[
                Profile(id="control", memory=None, candidate_score=None),
            ]
        ),
    )
    return original, selected, profile_path


def test_new_selection_uses_artifact_relative_symlink_alias(project):
    root, selected, _ = project
    _, metadata = load_selection(selected)
    assert metadata.path_base == "artifact"
    assert metadata.source_path == "../../creak/dev.jsonl"
    assert not Path(metadata.source_path).is_absolute()
    reference = resolve_reference(metadata.source_path, selected.parent, metadata.path_base)
    assert reference.resolve() == (root / "dataset" / "creak" / "dev.jsonl").resolve()
    assert str(root) not in metadata.model_dump_json()


def test_prepare_and_execution_work_after_move_and_from_different_cwd(
    project, tmp_path, monkeypatch
):
    root, selected, profiles = project
    original_prepared = root / "inputs" / "generated" / "v1"
    first = prepare_requests(selected, profiles, ["control"], original_prepared)
    moved = tmp_path / "moved"
    shutil.copytree(root, moved, symlinks=True)
    # Demonstrate preparation uses frozen selection metadata even without raw files.
    (moved / "dataset" / "creak").unlink()
    monkeypatch.chdir(tmp_path)
    second = prepare_requests(
        moved / selected.relative_to(root),
        moved / profiles.relative_to(root),
        ["control"],
        moved / "inputs" / "generated" / "v2",
    )
    assert first.preparation_sha256 == second.preparation_sha256
    assert first.requests_sha256 == second.requests_sha256
    assert first.manifest_sha256 == second.manifest_sha256
    assert first.path_base == "artifact"
    assert not Path(first.selection_path).is_absolute()
    assert not Path(first.profiles_path).is_absolute()
    assert verify_prepared(moved / "inputs" / "generated" / "v1") == first
    with LLMClient(
        ClientConfig(provider="openai", model="mock"), provider=FakeProvider()
    ) as client:
        assert (
            run_prepared(
                client, moved / "inputs" / "generated" / "v1", moved / "outputs" / "results.jsonl"
            )
            == 1
        )
        with pytest.raises(DataError, match="outside"):
            run_prepared(
                client,
                moved / "inputs" / "generated" / "v1",
                moved / "dataset" / "selected_data" / "set" / "results.jsonl",
            )


def test_legacy_absolute_metadata_still_loads_without_rewriting(project):
    root, selected, profiles = project
    _, metadata = load_selection(selected)
    legacy = metadata.model_copy(
        update={
            "path_base": None,
            "source_path": str((root / "dataset" / "creak" / "dev.jsonl").resolve()),
        }
    )
    save_json(metadata_path(selected), legacy)
    before = metadata_path(selected).read_bytes()
    loaded, reread = load_selection(selected)
    assert len(loaded) == 1 and reread.path_base is None
    assert resolve_reference(reread.source_path, selected.parent, None).is_absolute()
    prepare_requests(selected, profiles, ["control"], root / "prepared")
    assert metadata_path(selected).read_bytes() == before


def test_tracked_selection_paths_are_portable_and_claims_valid():
    root = Path(__file__).resolve().parents[1]
    for folder, name in (
        ("candidates", "candidate_claims"),
        ("curated_claims_bundle", "curated_claims"),
    ):
        selected = root / "dataset" / "selected_data" / folder / f"{name}.jsonl"
        claims, metadata = load_selection(selected)
        assert claims
        assert metadata.path_base == "artifact"
        assert not Path(metadata.source_path).is_absolute()
        assert (
            resolve_reference(metadata.source_path, selected.parent, metadata.path_base).resolve()
            == (root / "dataset" / "creak" / "dev.jsonl").resolve()
        )
