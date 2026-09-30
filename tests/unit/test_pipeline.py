from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from openinspect.ingest.extract import ExtractError
from openinspect.ingest.layout import source_dirs
from openinspect.ingest.pipeline import (
    IngestError,
    compute_cross_source,
    ensure_extracted,
    run_source,
)
from openinspect.ingest.report import SourceReport
from openinspect.provenance.registry import LoadedManifest, load_registry
from tests.conftest import Repo
from tests.factories import accepted_manifest, pending_manifest, with_value
from tests.ingest_fixtures import (
    DEF_BOXES,
    DEF_IMAGES,
    IND_BOXES,
    IND_IMAGES,
    build_pcb_defect,
    build_pcb_ind,
    zip_tree,
)


def prepare(
    repo: Repo,
    tmp_path: Path,
    slug: str,
    builder: Callable[[Path], None],
    *,
    content: dict[str, Any] | None = None,
    tweak: Callable[[Path], None] | None = None,
) -> tuple[LoadedManifest, Path]:
    """Build a synthetic archive, place it like ``ingest download`` would, and register its manifest."""
    tree = tmp_path / "work" / slug
    builder(tree)
    if tweak is not None:
        tweak(tree)
    archive = tmp_path / "data" / "raw" / slug / f"{slug}.zip"
    zip_tree(tree, archive)
    payload = archive.read_bytes()
    manifest = accepted_manifest(slug)
    manifest["acquisition"] = {
        "download_method": "http",
        "download_files": [
            {
                "url": "https://example.org/x.zip",
                "filename": archive.name,
                "bytes": len(payload),
                "record_checksum": {"algo": "sha256", "value": hashlib.sha256(payload).hexdigest()},
            }
        ],
        "download_date": None,
        "archive_sha256": None,
        "sha256_manifest": None,
    }
    if content:
        manifest["content"].update(content)
    repo.write_manifest(manifest)
    item = load_registry(repo.root).get(slug)
    assert item is not None
    return item, tmp_path / "data"


def test_a_source_is_ingested_end_to_end(repo: Repo, tmp_path: Path) -> None:
    item, data = prepare(repo, tmp_path, "pcb-defect", build_pcb_defect)
    report = run_source(item, repo_root=repo.root, data_dir=data)
    assert (report.images, report.annotations) == (DEF_IMAGES, DEF_BOXES)
    assert report.decode.failed == 0
    assert report.adapter.status == "ok"
    assert report.archive.size_ok is True
    assert report.archive.checksum_ok is True
    assert report.archive.zip_crc_ok is True
    assert [(c.label, c.count) for c in report.classes] == [("short", 3), ("spur", 2)]
    assert report.grouping.quality == "derived"
    assert report.licence.spdx == "CC-BY-4.0"
    assert report.licence.attribution_in_manifest is True
    assert report.licence.evidence_files == 1
    dirs = source_dirs(data, "pcb-defect")
    lines = (dirs.records / "images.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == DEF_IMAGES
    assert json.loads(lines[0])["source_dataset"] == "pcb-defect"
    assert (
        len((dirs.records / "annotations.jsonl").read_text(encoding="utf-8").splitlines())
        == DEF_BOXES
    )
    assert (
        report.digests["images_jsonl"]
        == hashlib.sha256((dirs.records / "images.jsonl").read_bytes()).hexdigest()
    )
    assert (
        report.digests["files_list"]
        == hashlib.sha256((dirs.records / "files.sha256").read_bytes()).hexdigest()
    )
    stored = repo.root / "manifests" / "ingest" / "pcb-defect" / "report.json"
    assert SourceReport.model_validate_json(stored.read_text(encoding="utf-8")) == report


def test_running_twice_gives_identical_output(repo: Repo, tmp_path: Path) -> None:
    item, data = prepare(repo, tmp_path, "pcb-defect", build_pcb_defect)
    run_source(item, repo_root=repo.root, data_dir=data)
    stored = repo.root / "manifests" / "ingest" / "pcb-defect" / "report.json"
    first = (
        stored.read_bytes(),
        (source_dirs(data, "pcb-defect").records / "images.jsonl").read_bytes(),
    )
    run_source(item, repo_root=repo.root, data_dir=data)
    second = (
        stored.read_bytes(),
        (source_dirs(data, "pcb-defect").records / "images.jsonl").read_bytes(),
    )
    assert first == second


def test_the_manifest_is_reconciled_with_what_was_observed(repo: Repo, tmp_path: Path) -> None:
    content = {
        "image_count": DEF_IMAGES,
        "annotation_count": 99,
        "original_classes": [{"label": "short", "count": 3}, {"label": "Spur", "count": 2}],
        "image_size_px": {"min": [64, 48], "max": [64, 48]},
    }
    item, data = prepare(repo, tmp_path, "pcb-defect", build_pcb_defect, content=content)
    rows = {r.field: r for r in run_source(item, repo_root=repo.root, data_dir=data).reconciliation}
    assert rows["content.image_count"].status == "match"
    assert rows["content.annotation_count"].status == "mismatch"
    assert rows["content.annotation_count"].observed == str(DEF_BOXES)
    assert rows["content.original_classes[short].count"].status == "match"
    assert (
        rows["content.original_classes[Spur].count"].status == "mismatch"
    )  # the source says 'spur'
    assert rows["content.original_classes[spur]"].status == "new"
    assert rows["content.image_size_px.min"].status == "match"


def test_official_split_counts_are_reconciled(repo: Repo, tmp_path: Path) -> None:
    content = {"official_splits": {"scheme": "8:1:1", "counts": {"train": 3, "val": 1, "test": 2}}}
    item, data = prepare(repo, tmp_path, "pcb-ind", build_pcb_ind, content=content)
    report = run_source(item, repo_root=repo.root, data_dir=data)
    assert (report.images, report.annotations) == (IND_IMAGES, IND_BOXES)
    rows = {r.field: r.status for r in report.reconciliation}
    assert rows["content.official_splits.counts.train"] == "match"
    assert rows["content.official_splits.counts.val"] == "match"
    assert rows["content.official_splits.counts.test"] == "mismatch"
    assert [(s.split, s.images) for s in report.splits] == [("train", 3), ("val", 1), ("test", 1)]
    assert report.splits[0].images_without_annotations == 1


def test_split_boxes_are_reconciled_with_the_boxes_key(repo: Repo, tmp_path: Path) -> None:
    content = {"official_splits": {"scheme": "x", "counts": {"train_images": 3, "train_boxes": 3}}}
    item, data = prepare(repo, tmp_path, "pcb-ind", build_pcb_ind, content=content)
    rows = {
        r.field: r.status
        for r in run_source(item, repo_root=repo.root, data_dir=data).reconciliation
    }
    assert rows["content.official_splits.counts.train_images"] == "match"
    assert rows["content.official_splits.counts.train_boxes"] == "match"


def test_exact_duplicates_inside_a_source_are_counted(repo: Repo, tmp_path: Path) -> None:
    def duplicate(tree: Path) -> None:
        images = sorted((tree / "PCB_Defect/images").iterdir())
        images[1].write_bytes(images[0].read_bytes())

    item, data = prepare(repo, tmp_path, "pcb-defect", build_pcb_defect, tweak=duplicate)
    duplicates = run_source(item, repo_root=repo.root, data_dir=data).exact_duplicates
    assert (duplicates.groups, duplicates.redundant_files) == (1, 1)


def test_a_duplicate_across_splits_is_recognised(repo: Repo, tmp_path: Path) -> None:
    def leak(tree: Path) -> None:
        train = tree / "YOLO/images/train/5771_b_001.jpg"
        for copy in (
            "YOLO/images/val/5773_b_001.jpg",
            "COCO/images/val/5773_b_001.jpg",
            "VOC/JPEGImages/5773_b_001.jpg",
        ):
            (tree / copy).write_bytes(train.read_bytes())

    item, data = prepare(repo, tmp_path, "pcb-ind", build_pcb_ind, tweak=leak)
    duplicates = run_source(item, repo_root=repo.root, data_dir=data).exact_duplicates
    assert duplicates.cross_split_groups == 1


def test_anomalies_of_the_adapter_reach_the_report(repo: Repo, tmp_path: Path) -> None:
    def zero_voc(tree: Path) -> None:
        (tree / "VOC/Annotations/5771_b_001.xml").write_bytes(b"\x00" * 249)

    item, data = prepare(repo, tmp_path, "pcb-ind", build_pcb_ind, tweak=zero_voc)
    report = run_source(item, repo_root=repo.root, data_dir=data)
    assert report.adapter.status == "ok_with_warnings"
    assert [(a.code, a.count) for a in report.anomalies] == [("voc_unreadable", 1)]


# ---------------------------------------------------------------------------------- errors


def test_only_accepted_sources_are_ingested(repo: Repo, tmp_path: Path) -> None:
    repo.write_manifest(pending_manifest("pcb-defect"))
    item = load_registry(repo.root).get("pcb-defect")
    assert item is not None
    with pytest.raises(IngestError, match="only accepted sources"):
        run_source(item, repo_root=repo.root, data_dir=tmp_path / "data")


def test_a_source_without_an_adapter_is_refused(repo: Repo, tmp_path: Path) -> None:
    repo.write_manifest(accepted_manifest("some-other-source"))
    item = load_registry(repo.root).get("some-other-source")
    assert item is not None
    with pytest.raises(IngestError, match="no adapter"):
        run_source(item, repo_root=repo.root, data_dir=tmp_path / "data")


def test_a_missing_archive_points_to_the_download_command(repo: Repo, tmp_path: Path) -> None:
    item, data = prepare(repo, tmp_path, "pcb-defect", build_pcb_defect)
    (data / "raw" / "pcb-defect" / "pcb-defect.zip").unlink()
    with pytest.raises(IngestError, match="ingest download pcb-defect"):
        run_source(item, repo_root=repo.root, data_dir=data)


def test_an_archive_that_no_longer_matches_the_record_is_refused(
    repo: Repo, tmp_path: Path
) -> None:
    item, data = prepare(repo, tmp_path, "pcb-defect", build_pcb_defect)
    archive = data / "raw" / "pcb-defect" / "pcb-defect.zip"
    archive.write_bytes(archive.read_bytes() + b"x")
    with pytest.raises(IngestError, match="does not match the repository record"):
        run_source(item, repo_root=repo.root, data_dir=data)


def test_an_archive_hash_that_differs_from_the_manifest_is_refused(
    repo: Repo, tmp_path: Path
) -> None:
    item, data = prepare(repo, tmp_path, "pcb-defect", build_pcb_defect)
    manifest = with_value(
        item.manifest.model_dump(mode="python"),
        "acquisition.archive_sha256",
        {"pcb-defect.zip": "0" * 64},
    )
    repo.write_manifest(manifest)
    changed = load_registry(repo.root).get("pcb-defect")
    assert changed is not None
    with pytest.raises(IngestError, match="differs from the one recorded"):
        run_source(changed, repo_root=repo.root, data_dir=data)


def test_exactly_one_archive_is_expected(repo: Repo, tmp_path: Path) -> None:
    item, data = prepare(repo, tmp_path, "pcb-defect", build_pcb_defect)
    dumped = item.manifest.model_dump(mode="python")
    dumped["acquisition"]["download_files"] = dumped["acquisition"]["download_files"] * 2
    repo.write_manifest(dumped)
    doubled = load_registry(repo.root).get("pcb-defect")
    assert doubled is not None
    with pytest.raises(IngestError, match="exactly one archive"):
        run_source(doubled, repo_root=repo.root, data_dir=data)


def test_a_layout_the_adapter_does_not_know_is_an_ingest_error(repo: Repo, tmp_path: Path) -> None:
    def drop_classes(tree: Path) -> None:
        (tree / "classes.json").unlink()

    item, data = prepare(repo, tmp_path, "pcb-ind", build_pcb_ind, tweak=drop_classes)
    with pytest.raises(IngestError, match="layout differs"):
        run_source(item, repo_root=repo.root, data_dir=data)


# ------------------------------------------------------------------------------ extraction


def test_the_hash_list_is_rebuilt_when_it_is_missing(repo: Repo, tmp_path: Path) -> None:
    item, data = prepare(repo, tmp_path, "pcb-defect", build_pcb_defect)
    dirs = source_dirs(data, "pcb-defect")
    archive = dirs.raw / "pcb-defect.zip"
    first = ensure_extracted(archive, dirs)
    assert first.extracted_now
    (dirs.records / "files.sha256").unlink()
    again = ensure_extracted(archive, dirs)
    assert not again.extracted_now
    assert again.files == first.files
    assert (dirs.records / "files.sha256").is_file()
    assert item.manifest.slug == "pcb-defect"


def test_a_tree_that_differs_from_its_hash_list_is_refused(repo: Repo, tmp_path: Path) -> None:
    _, data = prepare(repo, tmp_path, "pcb-defect", build_pcb_defect)
    dirs = source_dirs(data, "pcb-defect")
    ensure_extracted(dirs.raw / "pcb-defect.zip", dirs)
    (dirs.extracted / "PCB_Defect" / "stray.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ExtractError, match="files on disk"):
        ensure_extracted(dirs.raw / "pcb-defect.zip", dirs)


# ------------------------------------------------------------------------- cross-source


def write_records(data: Path, slug: str, items: list[tuple[str, str]]) -> None:
    path = source_dirs(data, slug).records / "images.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps({"sha256": sha, "source_item_id": name}) + "\n" for name, sha in items),
        encoding="utf-8",
    )


def test_cross_source_duplicates_are_found_by_hash(tmp_path: Path) -> None:
    write_records(tmp_path, "src-a", [("a/1.jpg", "1" * 64), ("a/2.jpg", "2" * 64)])
    write_records(tmp_path, "src-b", [("b/9.jpg", "2" * 64), ("b/8.jpg", "3" * 64)])
    write_records(tmp_path, "src-c", [("c/1.jpg", "4" * 64)])
    cross = compute_cross_source(tmp_path, ["src-a", "src-b", "src-c"])
    assert cross.shared_sha256 == 1
    assert cross.groups == [["src-a:a/2.jpg", "src-b:b/9.jpg"]]
    assert cross.images_per_source == {"src-a": 2, "src-b": 2, "src-c": 1}


def test_the_same_hash_twice_in_one_source_is_not_a_cross_source_duplicate(tmp_path: Path) -> None:
    write_records(tmp_path, "src-a", [("a/1.jpg", "1" * 64), ("a/2.jpg", "1" * 64)])
    write_records(tmp_path, "src-b", [("b/1.jpg", "5" * 64)])
    assert compute_cross_source(tmp_path, ["src-a", "src-b"]).shared_sha256 == 0
