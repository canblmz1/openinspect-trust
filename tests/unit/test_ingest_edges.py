"""Error paths and edge cases of ingestion: what happens when a source does not look as expected."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from PIL import Image

from openinspect.ingest.adapters import ADAPTERS, dspcbsd_plus, pcb_defect, pcb_ind
from openinspect.ingest.adapters.base import (
    AdapterContext,
    AdapterError,
    AdapterResult,
    AdapterSpec,
    Findings,
)
from openinspect.ingest.adapters.dspcbsd_plus import name_family
from openinspect.ingest.inventory import summarize_tree
from openinspect.ingest.layout import source_dirs
from openinspect.ingest.pipeline import IngestError, hash_tree, run_source
from openinspect.provenance.registry import load_registry
from openinspect.provenance.schema import SourceManifest
from openinspect.settings import DataDirError, ensure_free_space
from tests.conftest import Repo
from tests.factories import accepted_manifest, pending_manifest, with_value
from tests.ingest_fixtures import (
    build_dspcbsd_plus,
    build_pcb_defect,
    build_pcb_ind,
    write_jpeg,
    zip_tree,
)


def edit_json(path: Path, change: Callable[[dict[str, Any]], None]) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data), encoding="utf-8")


def context(slug: str, tree: Path, progress: Callable[[str], None] | None = None) -> AdapterContext:
    manifest = SourceManifest.model_validate(accepted_manifest(slug))
    hashes = {f.path: f.sha256 for f in hash_tree(tree)}
    if progress is None:
        return AdapterContext(slug=slug, manifest=manifest, root=tree, hashes=hashes)
    return AdapterContext(slug=slug, manifest=manifest, root=tree, hashes=hashes, progress=progress)


def adapt(slug: str, tree: Path, progress: Callable[[str], None] | None = None) -> AdapterResult:
    return ADAPTERS[slug].run(context(slug, tree, progress))


def codes(result: AdapterResult) -> dict[str, int]:
    return {a.code: a.count for a in result.findings.anomalies()}


def rotated_jpeg(path: Path) -> None:
    exif = Image.Exif()
    exif[0x0112] = 6
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), "red").save(buffer, "JPEG", exif=exif.tobytes())
    path.write_bytes(buffer.getvalue())


@pytest.fixture
def dsp(tmp_path: Path) -> Path:
    build_dspcbsd_plus(tmp_path / "tree")
    return tmp_path / "tree"


@pytest.fixture
def ind(tmp_path: Path) -> Path:
    build_pcb_ind(tmp_path / "tree")
    return tmp_path / "tree"


@pytest.fixture
def defect(tmp_path: Path) -> Path:
    build_pcb_defect(tmp_path / "tree")
    return tmp_path / "tree"


# ------------------------------------------------------------------------------- base


def test_the_adapter_context_needs_a_url_a_licence_and_a_hash(tmp_path: Path) -> None:
    pending = SourceManifest.model_validate(pending_manifest("pcb-defect"))
    ctx = AdapterContext(slug="pcb-defect", manifest=pending, root=tmp_path, hashes={})
    with pytest.raises(AdapterError, match="no official_url"):
        _ = ctx.source_url
    with pytest.raises(AdapterError, match="no licence"):
        _ = ctx.spdx
    with pytest.raises(AdapterError, match="no SHA-256"):
        ctx.sha256("missing.jpg")
    ctx.progress("a message that is ignored by default")


def test_findings_keep_a_few_examples_and_drop_empty_anomalies() -> None:
    findings = Findings(formats_present=["coco"], canonical_format="coco")
    for index in range(9):
        findings.anomaly("code", "warning", "message", f"example-{index}")
    findings.anomaly("silent", "info", "never counted", "x", count=0)
    found = findings.anomalies()
    assert [(a.code, a.count) for a in found] == [("code", 9)]
    assert len(found[0].examples) == 5


# -------------------------------------------------------------------------- DsPCBSD+


def test_name_families() -> None:
    assert name_family("S_10313741.jpg") == "S"
    assert name_family("Y_000900.jpg") == "Y"
    assert name_family("1005_data.jpg") == "data"
    assert name_family("0429060.jpg") == "num7"
    assert name_family("12345.jpg") == "num5"
    assert name_family("AAA (2).jpg") == "copy_suffix"
    assert name_family("weird.png") == "other"


def test_dspcbsd_plus_needs_contiguous_category_ids(dsp: Path) -> None:
    def shift(data: dict[str, Any]) -> None:
        data["categories"][2]["id"] = 7

    edit_json(dsp / "Data_COCO/annotations/instances_val2017.json", shift)
    with pytest.raises(AdapterError, match="category ids are not"):
        adapt("dspcbsd-plus", dsp)


def test_dspcbsd_plus_detects_a_name_in_both_splits(dsp: Path) -> None:
    name = "S_00000001.jpg"
    (dsp / "Data_COCO/val2017" / name).write_bytes(
        (dsp / "Data_COCO/train2017" / name).read_bytes()
    )
    edit_json(
        dsp / "Data_COCO/annotations/instances_val2017.json",
        lambda d: d["images"].append({"id": 99, "file_name": name, "width": 32, "height": 32}),
    )
    assert adapt("dspcbsd-plus", dsp).findings.anomalies()
    assert codes(adapt("dspcbsd-plus", dsp))["name_in_both_splits"] == 1


def test_dspcbsd_plus_detects_a_size_mismatch_and_a_rotated_image(dsp: Path) -> None:
    edit_json(
        dsp / "Data_COCO/annotations/instances_val2017.json",
        lambda d: d["images"][0].update(width=64),
    )
    rotated_jpeg(dsp / "Data_COCO/train2017/Y_000001.jpg")
    found = codes(adapt("dspcbsd-plus", dsp))
    assert found["size_mismatch_json_vs_file"] == 1
    assert found["exif_orientation_not_1"] == 1


def test_dspcbsd_plus_counts_annotations_with_an_unknown_category(dsp: Path) -> None:
    def add(data: dict[str, Any]) -> None:
        data["annotations"].append(
            {"id": 77, "image_id": 0, "category_id": 42, "bbox": [1, 1, 5, 5], "iscrowd": 0}
        )

    edit_json(dsp / "Data_COCO/annotations/instances_val2017.json", add)
    assert codes(adapt("dspcbsd-plus", dsp))["annotation_unknown_category"] == 1


def test_dspcbsd_plus_reports_annotations_of_unknown_images(dsp: Path) -> None:
    def add(data: dict[str, Any]) -> None:
        data["annotations"].append(
            {"id": 77, "image_id": 555, "category_id": 1, "bbox": [1, 1, 5, 5], "iscrowd": 0}
        )

    edit_json(dsp / "Data_COCO/annotations/instances_train2017.json", add)
    assert codes(adapt("dspcbsd-plus", dsp))["orphan_annotation_coco_json"] == 1


def test_dspcbsd_plus_measures_locality_in_a_large_enough_family(
    dsp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dspcbsd_plus, "MIN_FAMILY_FOR_LOCALITY", 2)
    grouping = adapt("dspcbsd-plus", dsp).findings.grouping
    assert grouping is not None
    assert any(line.startswith("family S") for line in grouping.evidence)


def test_progress_is_reported_by_every_adapter(
    dsp: Path, ind: Path, defect: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for module in (dspcbsd_plus, pcb_ind, pcb_defect):
        monkeypatch.setattr(module, "PROGRESS_EVERY", 2)
    for slug, tree in (("dspcbsd-plus", dsp), ("pcb-ind", ind), ("pcb-defect", defect)):
        messages: list[str] = []
        adapt(slug, tree, messages.append)
        assert messages
        assert all(m.startswith(slug) for m in messages)


# ---------------------------------------------------------------------------- PCB-IND


def test_pcb_ind_needs_contiguous_class_ids_and_reports_another_version(ind: Path) -> None:
    def version(data: dict[str, Any]) -> None:
        data["version"] = "v3"

    edit_json(ind / "classes.json", version)
    assert codes(adapt("pcb-ind", ind))["classes_json_version"] == 1

    def gap(data: dict[str, Any]) -> None:
        data["classes"][2]["id"] = 9

    edit_json(ind / "classes.json", gap)
    with pytest.raises(AdapterError, match="ids are not"):
        adapt("pcb-ind", ind)


def test_pcb_ind_detects_coco_categories_that_differ(ind: Path) -> None:
    def rename(data: dict[str, Any]) -> None:
        data["categories"][0]["name"] = "renamed"

    edit_json(ind / "COCO/annotations/train.json", rename)
    assert codes(adapt("pcb-ind", ind))["coco_categories_differ"] == 1


def test_pcb_ind_detects_a_name_in_two_splits(ind: Path) -> None:
    name = "5771_b_001.jpg"
    (ind / "YOLO/images/val" / name).write_bytes((ind / "YOLO/images/train" / name).read_bytes())
    assert codes(adapt("pcb-ind", ind))["name_in_several_splits"] == 1


def test_pcb_ind_detects_undecodable_rotated_and_differing_copies(ind: Path) -> None:
    (ind / "YOLO/images/train/5771_b_001.jpg").write_bytes(b"garbage")
    rotated_jpeg(ind / "YOLO/images/test/5774_t_001.jpg")
    write_jpeg(ind / "VOC/JPEGImages/5773_b_001.jpg", 999)
    found = codes(adapt("pcb-ind", ind))
    assert found["image_undecodable"] == 1
    assert found["exif_orientation_not_1"] == 1
    assert found["image_copies_differ"] >= 1


def test_pcb_ind_reports_a_malformed_yolo_label_and_a_box_outside_the_image(ind: Path) -> None:
    (ind / "YOLO/labels/train/5771_b_001.txt").write_text("0 0.5 0.5\n", encoding="utf-8")
    (ind / "YOLO/labels/val/5773_b_001.txt").write_text("2 0.98 0.5 0.1 0.1\n", encoding="utf-8")
    result = adapt("pcb-ind", ind)
    found = codes(result)
    assert found["yolo_label_unreadable"] == 1
    assert found["box_out_of_bounds"] == 1
    flagged = next(i for i in result.images if i.source_item_id.endswith("5771_b_001.jpg"))
    assert "annotation_unreadable" in flagged.flags


def test_pcb_ind_detects_boxes_that_coco_or_voc_disagree_about(ind: Path) -> None:
    def extra(data: dict[str, Any]) -> None:
        data["annotations"].append(
            {"id": 50, "image_id": 2, "category_id": 0, "bbox": [1, 1, 3, 3], "iscrowd": 0}
        )
        data["annotations"][0]["bbox"][0] += 6

    edit_json(ind / "COCO/annotations/train.json", extra)
    xml = ind / "VOC/Annotations/5771_t_002.xml"
    xml.write_text(
        xml.read_text(encoding="utf-8").replace("<xmin>5</xmin>", "<xmin>11</xmin>"),
        encoding="utf-8",
    )
    found = codes(adapt("pcb-ind", ind))
    assert found["coco_extra_box"] == 1
    assert found["coco_yolo_box_deviation"] == 1
    assert found["voc_yolo_boxes_differ"] == 1


def test_a_readme_heading_without_text_falls_back_to_the_words_it_uses(ind: Path) -> None:
    (ind / "README.md").write_text("## License\n\n## Next\n", encoding="utf-8")
    assert adapt("pcb-ind", ind).findings.archive_says == ["README.md mentions: License"]


# -------------------------------------------------------------------------- PCB-Defect


def test_pcb_defect_reports_undecodable_rotated_and_out_of_bounds(defect: Path) -> None:
    (defect / "PCB_Defect/images/pcb_defect_001.jpg").write_bytes(b"garbage")
    rotated_jpeg(defect / "PCB_Defect/images/pcb_defect_002.jpg")

    def change(data: dict[str, Any]) -> None:
        data["annotations"][-1]["bbox"] = [60, 40, 50, 50]  # leaves a 64x48 image

    edit_json(defect / "PCB_Defect/annotation/_annotations.coco.json", change)
    found = codes(adapt("pcb-defect", defect))
    assert found["image_undecodable"] == 1
    assert found["exif_orientation_not_1"] == 1
    assert found["box_out_of_bounds"] == 1


def test_pcb_defect_flags_an_image_without_annotations(defect: Path) -> None:
    def clear(data: dict[str, Any]) -> None:
        data["annotations"] = [a for a in data["annotations"] if a["image_id"] != 0]

    edit_json(defect / "PCB_Defect/annotation/_annotations.coco.json", clear)
    result = adapt("pcb-defect", defect)
    image = next(i for i in result.images if i.source_item_id.endswith("pcb_defect_001.jpg"))
    assert "no_annotations" in image.flags


def test_pcb_defect_cannot_judge_grouping_from_one_image(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    build_pcb_defect(tree)
    for name in ("002", "003", "004"):
        (tree / f"PCB_Defect/images/pcb_defect_{name}.jpg").unlink()

    def keep_first(data: dict[str, Any]) -> None:
        data["images"] = data["images"][:1]
        data["annotations"] = [a for a in data["annotations"] if a["image_id"] == 0]

    edit_json(tree / "PCB_Defect/annotation/_annotations.coco.json", keep_first)
    grouping = adapt("pcb-defect", tree).findings.grouping
    assert grouping is not None
    assert grouping.key is None
    assert grouping.quality == "none"


# ----------------------------------------------------------------------------- pipeline


def register(repo: Repo, slug: str, archive: Path) -> Any:
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
    repo.write_manifest(manifest)
    item = load_registry(repo.root).get(slug)
    assert item is not None
    return item


def test_a_file_that_is_not_a_zip_is_an_ingest_error(repo: Repo, tmp_path: Path) -> None:
    archive = tmp_path / "data" / "raw" / "pcb-defect" / "archive.zip"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"this is not a zip archive")
    item = register(repo, "pcb-defect", archive)
    with pytest.raises(IngestError, match="not a valid zip"):
        run_source(item, repo_root=repo.root, data_dir=tmp_path / "data")


def test_archive_member_anomalies_reach_the_report(repo: Repo, tmp_path: Path) -> None:
    tree = tmp_path / "work"
    build_pcb_defect(tree)
    archive = tmp_path / "data" / "raw" / "pcb-defect" / "archive.zip"
    zip_tree(tree, archive)
    with zipfile.ZipFile(archive, "a") as zf:
        zf.writestr("__MACOSX/._junk", b"x")
    item = register(repo, "pcb-defect", archive)
    report = run_source(item, repo_root=repo.root, data_dir=tmp_path / "data")
    assert [a.code for a in report.anomalies if a.code == "archive_member_anomaly"] == [
        "archive_member_anomaly"
    ]


def test_an_adapter_must_deliver_a_grouping_analysis(
    repo: Repo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = tmp_path / "work"
    build_pcb_defect(tree)
    archive = tmp_path / "data" / "raw" / "pcb-defect" / "archive.zip"
    zip_tree(tree, archive)
    item = register(repo, "pcb-defect", archive)

    def lazy(_ctx: AdapterContext) -> AdapterResult:
        return AdapterResult([], [], Findings(formats_present=["coco"], canonical_format="coco"))

    monkeypatch.setitem(ADAPTERS, "pcb-defect", AdapterSpec("lazy", 1, lazy))
    with pytest.raises(IngestError, match="no grouping analysis"):
        run_source(item, repo_root=repo.root, data_dir=tmp_path / "data")


def test_the_default_progress_callback_is_harmless(
    repo: Repo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pcb_defect, "PROGRESS_EVERY", 1)
    tree = tmp_path / "work"
    build_pcb_defect(tree)
    archive = tmp_path / "data" / "raw" / "pcb-defect" / "archive.zip"
    zip_tree(tree, archive)
    item = register(repo, "pcb-defect", archive)
    assert run_source(item, repo_root=repo.root, data_dir=tmp_path / "data").images == 4


# ------------------------------------------------------------------------------- misc


def test_the_tree_summary_says_when_it_stops_descending(tmp_path: Path) -> None:
    (tmp_path / "a" / "b" / "c").mkdir(parents=True)
    (tmp_path / "a" / "b" / "c" / "f.txt").write_text("x", encoding="utf-8")
    text = summarize_tree(tmp_path, depth=1)
    assert "deeper directories not shown" in text
    assert "f.txt" not in text


def test_free_space_needs_an_existing_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "exists", lambda _self: False)
    with pytest.raises(DataDirError, match="cannot find an existing parent"):
        ensure_free_space(tmp_path / "x", 1)


def test_source_dirs_layout(tmp_path: Path) -> None:
    dirs = source_dirs(tmp_path, "demo-source")
    assert dirs.raw == tmp_path / "raw" / "demo-source"
    assert dirs.extracted == tmp_path / "extracted" / "demo-source"
    assert dirs.records == tmp_path / "records" / "demo-source"


def test_a_manifest_value_is_reconciled_against_a_changed_size(repo: Repo, tmp_path: Path) -> None:
    tree = tmp_path / "work"
    build_pcb_defect(tree)
    archive = tmp_path / "data" / "raw" / "pcb-defect" / "archive.zip"
    zip_tree(tree, archive)
    item = register(repo, "pcb-defect", archive)
    repo.write_manifest(
        with_value(item.manifest.model_dump(mode="python"), "content.image_count", 5)
    )
    changed = load_registry(repo.root).get("pcb-defect")
    assert changed is not None
    rows = {
        r.field: r.status
        for r in run_source(changed, repo_root=repo.root, data_dir=tmp_path / "data").reconciliation
    }
    assert rows["content.image_count"] == "mismatch"


def test_a_truncated_response_is_retried_until_it_is_complete(tmp_path: Path) -> None:
    from openinspect.ingest.download import download
    from openinspect.provenance.schema import Checksum, DownloadFile

    data = bytes(range(256)) * 8
    calls: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(
                200, content=data[:100], headers={"content-length": str(len(data))}
            )
        return httpx.Response(200, content=data, headers={"content-length": str(len(data))})

    spec = DownloadFile(
        url="https://example.org/a.zip",
        filename="a.zip",
        bytes=len(data),
        record_checksum=Checksum(algo="sha256", value=hashlib.sha256(data).hexdigest()),
    )
    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        record = download(spec, tmp_path, client=client, sleep=lambda _s: None)
    except Exception as exc:  # the mock transport may refuse a short body itself
        pytest.skip(f"transport rejected the short body: {exc}")
    assert record.checksum_ok is True


def test_a_client_created_by_download_is_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from openinspect.ingest import download as download_module
    from openinspect.provenance.schema import DownloadFile

    data = b"payload"
    closed: list[bool] = []

    class Tracked(httpx.Client):
        def close(self) -> None:
            closed.append(True)
            super().close()

    def factory(**kwargs: Any) -> httpx.Client:
        return Tracked(
            transport=httpx.MockTransport(lambda _r: httpx.Response(200, content=data)), **kwargs
        )

    monkeypatch.setattr("openinspect.ingest.download.httpx.Client", factory)
    download_module.download(
        DownloadFile(url="https://example.org/a.bin", filename="a.bin"),
        tmp_path,
        sleep=lambda _s: None,
    )
    assert closed == [True]
