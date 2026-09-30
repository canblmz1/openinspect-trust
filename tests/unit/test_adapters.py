from __future__ import annotations

import json
from pathlib import Path

import pytest

from openinspect.ingest.adapters import ADAPTERS
from openinspect.ingest.adapters.base import AdapterContext, AdapterError, AdapterResult
from openinspect.ingest.pipeline import hash_tree
from openinspect.provenance.schema import SourceManifest
from tests.factories import accepted_manifest
from tests.ingest_fixtures import (
    DEF_BOXES,
    DEF_IMAGES,
    DSP_BOXES,
    DSP_IMAGES,
    IND_BOXES,
    IND_IMAGES,
    build_dspcbsd_plus,
    build_pcb_defect,
    build_pcb_ind,
)


def run_adapter(slug: str, tree: Path) -> AdapterResult:
    manifest = SourceManifest.model_validate(accepted_manifest(slug))
    hashes = {f.path: f.sha256 for f in hash_tree(tree)}
    return ADAPTERS[slug].run(
        AdapterContext(slug=slug, manifest=manifest, root=tree, hashes=hashes)
    )


def codes(result: AdapterResult) -> dict[str, int]:
    return {a.code: a.count for a in result.findings.anomalies()}


# -------------------------------------------------------------------------------- DsPCBSD+


@pytest.fixture
def dsp(tmp_path: Path) -> Path:
    build_dspcbsd_plus(tmp_path / "tree")
    return tmp_path / "tree"


def test_dspcbsd_plus_clean_archive(dsp: Path) -> None:
    result = run_adapter("dspcbsd-plus", dsp)
    assert len(result.images) == DSP_IMAGES
    assert len(result.annotations) == DSP_BOXES
    assert all(i.decode_ok for i in result.images)
    assert {i.original_split for i in result.images} == {"train", "val"}
    assert codes(result) == {
        "non_data_file_in_archive": 1,
        "voc_not_shipped": 1,
        "windows_copy_suffix_in_name": 1,
    }
    assert result.findings.canonical_format == "coco"
    assert result.findings.formats_present == ["coco", "yolo"]


def test_dspcbsd_plus_records_carry_provenance_and_the_identical_copy(dsp: Path) -> None:
    result = run_adapter("dspcbsd-plus", dsp)
    image = next(i for i in result.images if i.source_item_id.endswith("S_00000001.jpg"))
    assert image.source_item_id == "Data_COCO/train2017/S_00000001.jpg"
    assert image.alternate_paths == ["Data_YOLO/images/train/S_00000001.jpg"]
    assert image.source_dataset == "dspcbsd-plus"
    assert image.source_license == "CC-BY-4.0"
    assert image.source_url == "https://zenodo.org/records/1"
    assert image.sha256 == image.sha256_source
    assert image.n_annotations == 2
    assert image.original_labels == ["SH", "SP"]
    assert image.name_family == "S"
    assert image.source_group_id is None  # no reliable board key in this source
    assert image.dhash is not None
    assert len(image.dhash) == 16


def test_dspcbsd_plus_flags_images_without_boxes(dsp: Path) -> None:
    result = run_adapter("dspcbsd-plus", dsp)
    empty = next(i for i in result.images if i.source_item_id.endswith("0000001.jpg"))
    assert "no_annotations" in empty.flags


def test_dspcbsd_plus_says_no_grouping_key_exists(dsp: Path) -> None:
    grouping = run_adapter("dspcbsd-plus", dsp).findings.grouping
    assert grouping is not None
    assert grouping.key is None
    assert grouping.quality == "none"
    assert any("families" in line for line in grouping.evidence)


def test_dspcbsd_plus_detects_orphans_and_a_disagreeing_yolo_copy(dsp: Path) -> None:
    (dsp / "Data_YOLO/labels/train/Y_000001.txt").unlink()
    (dsp / "Data_YOLO/images/val/S_00000009.jpg").unlink()
    extra = dsp / "Data_COCO/val2017/X_000000.jpg"
    extra.write_bytes((dsp / "Data_COCO/val2017/E_000002.jpg").read_bytes())
    found = codes(run_adapter("dspcbsd-plus", dsp))
    assert found["orphan_image_coco_dir_not_in_yolo_labels"] == 2  # Y_000001 and the new file
    assert (
        found["orphan_image_coco_dir_not_in_yolo_images"] == 2
    )  # the removed copy and the new file
    assert found["orphan_image_coco_dir_not_in_coco_json"] == 1


def test_dspcbsd_plus_detects_a_corrupt_image_and_differing_copies(dsp: Path) -> None:
    (dsp / "Data_COCO/train2017/Y_000001.jpg").write_bytes(b"not a jpeg at all")
    found = codes(run_adapter("dspcbsd-plus", dsp))
    assert found["image_undecodable"] == 1
    assert found["image_copies_differ"] == 1


def test_dspcbsd_plus_detects_box_disagreement_between_coco_and_yolo(dsp: Path) -> None:
    label = dsp / "Data_YOLO/labels/train/S_00000001.txt"
    label.write_text("0 0.9 0.9 0.1 0.1\n1 0.5 0.5 0.4 0.6\n", encoding="utf-8")
    found = codes(run_adapter("dspcbsd-plus", dsp))
    assert found["coco_yolo_box_deviation"] == 1


def test_dspcbsd_plus_detects_box_count_disagreement(dsp: Path) -> None:
    (dsp / "Data_YOLO/labels/val/S_00000009.txt").write_text(
        "1 0.5 0.5 0.2 0.2\n", encoding="utf-8"
    )
    assert codes(run_adapter("dspcbsd-plus", dsp))["coco_yolo_box_count_differs"] == 1


def test_dspcbsd_plus_reports_a_malformed_yolo_label(dsp: Path) -> None:
    (dsp / "Data_YOLO/labels/val/E_000002.txt").write_text("1 0.5 0.5\n", encoding="utf-8")
    assert codes(run_adapter("dspcbsd-plus", dsp))["yolo_label_unreadable"] == 1


def test_dspcbsd_plus_flags_a_box_outside_the_image(dsp: Path) -> None:
    path = dsp / "Data_COCO/annotations/instances_val2017.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["annotations"][0]["bbox"] = [20, 20, 50, 50]
    path.write_text(json.dumps(data), encoding="utf-8")
    assert codes(run_adapter("dspcbsd-plus", dsp))["box_out_of_bounds"] == 1


def test_dspcbsd_plus_refuses_a_layout_it_was_not_written_for(dsp: Path) -> None:
    (dsp / "Data_COCO/annotations/instances_val2017.json").unlink()
    with pytest.raises(AdapterError, match="layout differs"):
        run_adapter("dspcbsd-plus", dsp)


# ---------------------------------------------------------------------------------- PCB-IND


@pytest.fixture
def ind(tmp_path: Path) -> Path:
    build_pcb_ind(tmp_path / "tree")
    return tmp_path / "tree"


def test_pcb_ind_clean_archive(ind: Path) -> None:
    result = run_adapter("pcb-ind", ind)
    assert len(result.images) == IND_IMAGES
    assert len(result.annotations) == IND_BOXES
    assert {i.original_split for i in result.images} == {"train", "val", "test"}
    assert codes(result) == {}
    assert result.findings.canonical_format == "yolo"
    assert result.findings.formats_present == ["coco", "voc", "yolo"]
    assert result.findings.archive_says == ["README.md does not state a licence"]


def test_pcb_ind_records_groups_and_copies(ind: Path) -> None:
    result = run_adapter("pcb-ind", ind)
    image = next(i for i in result.images if i.source_item_id.endswith("5771_t_002.jpg"))
    assert image.source_item_id == "YOLO/images/train/5771_t_002.jpg"
    assert sorted(image.alternate_paths) == [
        "COCO/images/train/5771_t_002.jpg",
        "VOC/JPEGImages/5771_t_002.jpg",
    ]
    assert image.source_group_id == "5771"
    assert image.source_subgroup_id == "5771_t"
    assert image.original_labels == ["missing_copper", "scratch"]
    empty = next(i for i in result.images if i.source_item_id.endswith("5772_b_003.jpg"))
    assert "no_annotations" in empty.flags


def test_pcb_ind_grouping_evidence_counts_batches_across_splits(ind: Path) -> None:
    grouping = run_adapter("pcb-ind", ind).findings.grouping
    assert grouping is not None
    assert grouping.quality == "explicit"
    assert grouping.n_groups == 4  # batches 5771..5774
    assert any(
        "(batch, side) groups that occur in more than one split: 0" in e for e in grouping.evidence
    )


def test_pcb_ind_detects_the_zeroed_voc_file(ind: Path) -> None:
    (ind / "VOC/Annotations/5771_b_001.xml").write_bytes(b"\x00" * 249)
    result = run_adapter("pcb-ind", ind)
    found = codes(result)
    assert found["voc_unreadable"] == 1
    image = next(i for i in result.images if i.source_item_id.endswith("5771_b_001.jpg"))
    assert "voc_unreadable" in image.flags
    assert len(result.annotations) == IND_BOXES  # YOLO still holds every box


def test_pcb_ind_detects_a_box_missing_from_coco(ind: Path) -> None:
    path = ind / "COCO/annotations/train.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["annotations"] = data["annotations"][:-1]
    path.write_text(json.dumps(data), encoding="utf-8")
    result = run_adapter("pcb-ind", ind)
    assert codes(result)["coco_missing_box"] == 1
    assert len(result.annotations) == IND_BOXES


def test_pcb_ind_detects_orphans_across_formats(ind: Path) -> None:
    (ind / "YOLO/labels/train/5772_b_003.txt").unlink()
    (ind / "VOC/Annotations/5774_t_001.xml").unlink()
    found = codes(run_adapter("pcb-ind", ind))
    assert found["orphan_image_yolo_images_not_in_yolo_labels"] == 1
    assert found["orphan_annotation_yolo_images_not_in_voc_annotations"] == 1


def test_pcb_ind_detects_a_class_map_conflict(ind: Path) -> None:
    (ind / "YOLO/data.yaml").write_text("names:\n- a\n- b\n- c\n", encoding="utf-8")
    assert codes(run_adapter("pcb-ind", ind))["class_map_conflict"] == 1


def test_pcb_ind_flags_names_that_break_the_batch_pattern(ind: Path) -> None:
    for folder in ("YOLO/images/test", "COCO/images/test", "VOC/JPEGImages"):
        if folder == "VOC/JPEGImages":
            (ind / folder / "5774_t_001.jpg").rename(ind / folder / "weird.jpg")
        else:
            (ind / folder / "5774_t_001.jpg").rename(ind / folder / "weird.jpg")
    (ind / "YOLO/labels/test/5774_t_001.txt").rename(ind / "YOLO/labels/test/weird.txt")
    found = codes(run_adapter("pcb-ind", ind))
    assert found["name_pattern_mismatch"] == 1


def test_pcb_ind_warns_when_the_readme_mentions_a_licence(ind: Path) -> None:
    (ind / "README.md").write_text(
        "Released under CC BY 4.0. License: see record.\n", encoding="utf-8"
    )
    says = run_adapter("pcb-ind", ind).findings.archive_says
    assert says
    assert "CC BY" in says[0]


def test_pcb_ind_records_what_the_readme_licence_section_says(ind: Path) -> None:
    (ind / "README.md").write_text(
        "# Title\n\n## License\n\nPlease use the license specified in the Zenodo record.\n\n## Notes\n\nx\n",
        encoding="utf-8",
    )
    says = run_adapter("pcb-ind", ind).findings.archive_says
    assert says == [
        "README.md section 'License' says: Please use the license specified in the Zenodo record."
    ]


def test_pcb_ind_refuses_a_layout_it_was_not_written_for(ind: Path) -> None:
    (ind / "classes.json").unlink()
    with pytest.raises(AdapterError, match="layout differs"):
        run_adapter("pcb-ind", ind)


# ------------------------------------------------------------------------------ PCB-Defect


@pytest.fixture
def pcb_defect(tmp_path: Path) -> Path:
    build_pcb_defect(tmp_path / "tree")
    return tmp_path / "tree"


def test_pcb_defect_clean_archive(pcb_defect: Path) -> None:
    result = run_adapter("pcb-defect", pcb_defect)
    assert len(result.images) == DEF_IMAGES
    assert len(result.annotations) == DEF_BOXES
    assert {i.original_split for i in result.images} == {None}
    assert codes(result) == {"unused_category": 1}
    assert result.findings.archive_says == [
        "COCO file states licence 'CC BY 4.0' (https://creativecommons.org/licenses/by/4.0/)"
    ]


def test_pcb_defect_keeps_the_original_name_and_derives_groups(pcb_defect: Path) -> None:
    result = run_adapter("pcb-defect", pcb_defect)
    image = next(i for i in result.images if i.source_item_id.endswith("pcb_defect_002.jpg"))
    assert image.original_name == "61-1-2.png"
    assert image.source_group_id == "61"
    assert image.source_subgroup_id == "61-1"
    grouping = result.findings.grouping
    assert grouping is not None
    assert grouping.quality == "derived"
    assert grouping.n_groups == 2
    assert any("nearest neighbour" in line for line in grouping.evidence)


def test_pcb_defect_reports_an_unparseable_original_name(pcb_defect: Path) -> None:
    path = pcb_defect / "PCB_Defect/annotation/_annotations.coco.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["images"][0]["extra"]["name"] = "board-A.png"
    path.write_text(json.dumps(data), encoding="utf-8")
    result = run_adapter("pcb-defect", pcb_defect)
    assert codes(result)["original_name_unparsed"] == 1
    assert (
        next(i for i in result.images if i.original_name == "board-A.png").source_group_id is None
    )


def test_pcb_defect_detects_orphans_and_size_mismatch(pcb_defect: Path) -> None:
    (pcb_defect / "PCB_Defect/images/pcb_defect_004.jpg").unlink()
    (pcb_defect / "PCB_Defect/images/stray.jpg").write_bytes(
        (pcb_defect / "PCB_Defect/images/pcb_defect_001.jpg").read_bytes()
    )
    path = pcb_defect / "PCB_Defect/annotation/_annotations.coco.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["images"][0]["width"] = 999
    path.write_text(json.dumps(data), encoding="utf-8")
    found = codes(run_adapter("pcb-defect", pcb_defect))
    assert found["orphan_image_coco_json_not_in_images_dir"] == 1
    assert found["orphan_image_images_dir_not_in_coco_json"] == 1
    assert found["size_mismatch_json_vs_file"] == 1


def test_pcb_defect_reports_annotations_of_unknown_images(pcb_defect: Path) -> None:
    path = pcb_defect / "PCB_Defect/annotation/_annotations.coco.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["annotations"].append(
        {"id": 99, "image_id": 77, "category_id": 1, "bbox": [1, 1, 5, 5], "iscrowd": 0}
    )
    path.write_text(json.dumps(data), encoding="utf-8")
    assert codes(run_adapter("pcb-defect", pcb_defect))["orphan_annotation_coco_json"] == 1


def test_every_accepted_source_has_an_adapter() -> None:
    assert set(ADAPTERS) == {"dspcbsd-plus", "pcb-ind", "pcb-defect"}
    assert all(spec.version >= 1 for spec in ADAPTERS.values())
