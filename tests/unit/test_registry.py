from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from openinspect.provenance.registry import (
    DuplicateSourceError,
    add_manifest,
    dump_manifest,
    find_repo_root,
    load_registry,
    parse_manifest_text,
    rel_path,
)
from openinspect.provenance.schema import SourceManifest
from tests.conftest import Repo
from tests.factories import accepted_manifest, pending_manifest


def _codes(registry_issues: tuple[object, ...]) -> list[str]:
    return [getattr(issue, "code", "") for issue in registry_issues]


# ---------------------------------------------------------------------- loading


def test_load_registry_reads_valid_manifests(repo: Repo) -> None:
    repo.write_manifest(accepted_manifest())
    repo.write_manifest(pending_manifest())
    registry = load_registry(repo.root)
    assert registry.issues == ()
    assert registry.slugs == ["demo-pending", "demo-source"]
    found = registry.get("demo-source")
    assert found is not None
    assert found.manifest.status == "accepted"
    assert registry.get("missing") is None


def test_files_starting_with_an_underscore_are_templates(repo: Repo) -> None:
    (repo.sources / "_template.yaml").write_text("not: [valid", encoding="utf-8")
    registry = load_registry(repo.root)
    assert registry.loaded == ()
    assert registry.issues == ()


def test_a_missing_manifests_directory_is_an_empty_registry(tmp_path: Path) -> None:
    registry = load_registry(tmp_path)
    assert registry.loaded == ()
    assert registry.issues == ()


def test_yaml_syntax_errors_are_reported_with_the_file(repo: Repo) -> None:
    (repo.sources / "broken.yaml").write_text("a: [1, 2", encoding="utf-8")
    registry = load_registry(repo.root)
    assert _codes(registry.issues) == ["E_YAML"]
    assert registry.issues[0].where == "manifests/sources/broken.yaml"


def test_the_top_level_must_be_a_mapping(repo: Repo) -> None:
    (repo.sources / "list.yaml").write_text("- a\n- b\n", encoding="utf-8")
    registry = load_registry(repo.root)
    assert _codes(registry.issues) == ["E_YAML"]
    assert "mapping" in registry.issues[0].message


def test_the_slug_must_match_the_file_name(repo: Repo) -> None:
    repo.write_manifest(accepted_manifest(), name="another-name")
    registry = load_registry(repo.root)
    assert _codes(registry.issues) == ["E_SLUG_FILENAME"]


def test_a_slug_declared_in_two_files_is_a_duplicate(repo: Repo) -> None:
    repo.write_manifest(accepted_manifest(), name="demo-source")
    repo.write_manifest(accepted_manifest(), name="copy")
    codes = _codes(load_registry(repo.root).issues)
    assert "E_DUPLICATE_SLUG" in codes
    assert "E_SLUG_FILENAME" in codes


def test_every_schema_problem_becomes_an_issue_that_keeps_the_slug(repo: Repo) -> None:
    data = pending_manifest()
    data["licence"] = {"spdx": "bad spdx!", "redistribution": "maybe"}
    repo.write_manifest(data)
    issues = load_registry(repo.root).issues
    assert _codes(issues) == ["E_SCHEMA", "E_SCHEMA"]
    assert {issue.slug for issue in issues} == {"demo-pending"}
    messages = " ".join(issue.message for issue in issues)
    assert "licence.spdx" in messages
    assert "licence.redistribution" in messages


def test_parse_manifest_text_returns_the_manifest_or_issues() -> None:
    good, no_issues = parse_manifest_text(yaml.safe_dump(pending_manifest()))
    assert good is not None
    assert no_issues == []
    bad, issues = parse_manifest_text("slug: demo\nstatus: pending\n", "x.yaml")
    assert bad is None
    assert issues
    assert issues[0].where == "x.yaml"


# ---------------------------------------------------------------------- writing


def test_add_manifest_writes_a_file_that_round_trips(tmp_path: Path) -> None:
    manifest = SourceManifest.model_validate(accepted_manifest())
    target = add_manifest(tmp_path, manifest)
    assert target == tmp_path / "manifests" / "sources" / "demo-source.yaml"
    assert target.read_text(encoding="utf-8").startswith("# Source manifest written by")
    registry = load_registry(tmp_path)
    assert registry.issues == ()
    loaded = registry.get("demo-source")
    assert loaded is not None
    assert loaded.manifest == manifest
    assert [p.name for p in target.parent.iterdir()] == ["demo-source.yaml"]  # no temp files


def test_dump_keeps_dates_as_dates_and_the_key_order() -> None:
    text = dump_manifest(SourceManifest.model_validate(accepted_manifest()))
    assert "published_on: 2026-01-01" in text
    assert text.index("slug:") < text.index("identity:") < text.index("licence:")


def test_add_manifest_refuses_a_duplicate(tmp_path: Path) -> None:
    manifest = SourceManifest.model_validate(pending_manifest())
    add_manifest(tmp_path, manifest)
    with pytest.raises(DuplicateSourceError, match="already exists"):
        add_manifest(tmp_path, manifest)


def test_force_replaces_the_file_with_the_same_slug(tmp_path: Path) -> None:
    first = SourceManifest.model_validate(pending_manifest())
    add_manifest(tmp_path, first)
    second = first.model_copy(update={"dataset_name": "Renamed"})
    add_manifest(tmp_path, second, force=True)
    loaded = load_registry(tmp_path).get("demo-pending")
    assert loaded is not None
    assert loaded.manifest.dataset_name == "Renamed"


def test_force_never_creates_a_second_file_for_one_slug(tmp_path: Path) -> None:
    manifest = SourceManifest.model_validate(pending_manifest())
    sources = tmp_path / "manifests" / "sources"
    sources.mkdir(parents=True)
    (sources / "other.yaml").write_text(yaml.safe_dump(pending_manifest()), encoding="utf-8")
    with pytest.raises(
        DuplicateSourceError, match=r"already declared in manifests/sources/other\.yaml"
    ):
        add_manifest(tmp_path, manifest, force=True)


# ---------------------------------------------------------------------- helpers


def test_find_repo_root_walks_up_to_the_manifests_directory(tmp_path: Path) -> None:
    (tmp_path / "manifests" / "sources").mkdir(parents=True)
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert find_repo_root(nested) == tmp_path.resolve()


def test_find_repo_root_falls_back_to_the_start_directory(tmp_path: Path) -> None:
    assert find_repo_root(tmp_path) == tmp_path.resolve()


def test_rel_path_handles_paths_outside_the_root(tmp_path: Path) -> None:
    inside = tmp_path / "a" / "b.txt"
    assert rel_path(inside, tmp_path) == "a/b.txt"
    outside = tmp_path.parent / "elsewhere.txt"
    assert rel_path(outside, tmp_path) == outside.as_posix()


def test_a_failed_write_leaves_neither_a_partial_file_nor_temp_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(src: object, dst: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("openinspect.provenance.registry.os.replace", boom)
    with pytest.raises(OSError, match="disk full"):
        add_manifest(tmp_path, SourceManifest.model_validate(pending_manifest()))
    assert list((tmp_path / "manifests" / "sources").iterdir()) == []
