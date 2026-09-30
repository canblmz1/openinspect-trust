from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from openinspect.ingest.formats import FormatError, load_coco, parse_voc, parse_yolo_label


def write_coco(path: Path, **overrides: Any) -> Path:
    data: dict[str, Any] = {
        "licenses": [
            {"id": 1, "name": "CC BY 4.0", "url": "https://creativecommons.org/licenses/by/4.0/"}
        ],
        "categories": [
            {"id": 0, "name": "placeholder"},
            {"id": 1, "name": "short"},
            {"id": 2, "name": "spur"},
        ],
        "images": [
            {
                "id": 10,
                "file_name": "a.jpg",
                "width": 100,
                "height": 50,
                "extra": {"name": "61-1-1.png"},
            },
            {"id": 11, "file_name": "b.jpg", "width": 100, "height": 50},
        ],
        "annotations": [
            {"id": 1, "image_id": 10, "category_id": 1, "bbox": [10, 5, 20, 10]},
            {"id": 2, "image_id": 10, "category_id": 2, "bbox": [1, 2, 3, 4]},
        ],
    }
    data.update(overrides)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_coco_boxes_are_converted_to_pixel_corners(tmp_path: Path) -> None:
    coco = load_coco(write_coco(tmp_path / "c.json"))
    assert [i.file_name for i in coco.images] == ["a.jpg", "b.jpg"]
    assert coco.images[0].extra_name == "61-1-1.png"
    assert coco.images[1].extra_name is None
    box = coco.boxes[10][0]
    assert (box.label, box.label_id, box.xyxy) == ("short", 1, (10.0, 5.0, 30.0, 15.0))
    assert 11 not in coco.boxes
    assert coco.annotation_count == 2
    assert coco.category_annotation_counts == {1: 1, 2: 1}
    assert coco.licences[0]["name"] == "CC BY 4.0"


def test_coco_counts_annotations_of_unknown_images_and_categories(tmp_path: Path) -> None:
    annotations = [
        {"id": 1, "image_id": 99, "category_id": 1, "bbox": [0, 0, 1, 1]},
        {"id": 2, "image_id": 10, "category_id": 42, "bbox": [0, 0, 1, 1]},
    ]
    coco = load_coco(write_coco(tmp_path / "c.json", annotations=annotations))
    assert coco.orphan_annotations == 1
    assert coco.unknown_category_annotations == 1
    assert coco.boxes == {}


@pytest.mark.parametrize("missing", ["categories", "images", "annotations"])
def test_coco_requires_its_lists(tmp_path: Path, missing: str) -> None:
    path = write_coco(tmp_path / "c.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    del data[missing]
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(FormatError, match=missing):
        load_coco(path)


def test_coco_rejects_files_that_are_not_json_objects(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(FormatError, match="cannot read JSON"):
        load_coco(broken)
    listing = tmp_path / "list.json"
    listing.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(FormatError, match="not an object"):
        load_coco(listing)


NAMES = ["mouse_bite", "short"]


def test_yolo_labels_are_converted_to_pixel_corners(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_text("1 0.5 0.5 0.2 0.4\n\n0 0.25 0.5 0.1 0.2\n", encoding="utf-8")
    boxes = parse_yolo_label(path, 100, 50, NAMES)
    assert boxes[0].label == "short"
    assert boxes[0].xyxy == pytest.approx((40.0, 15.0, 60.0, 35.0))
    assert boxes[1].label_id == 0


def test_an_empty_yolo_file_means_no_boxes(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_text("", encoding="utf-8")
    assert parse_yolo_label(path, 100, 50, NAMES) == []


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("1 0.5 0.5 0.2\n", "expected 5 values"),
        ("1 0.5 0.5 0.2 0.4 0.9\n", "expected 5 values"),
        ("x 0.5 0.5 0.2 0.4\n", "non-numeric"),
        ("1 0.5 abc 0.2 0.4\n", "non-numeric"),
        ("5 0.5 0.5 0.2 0.4\n", "class id 5"),
        ("-1 0.5 0.5 0.2 0.4\n", "class id -1"),
    ],
)
def test_malformed_yolo_lines_are_reported_with_their_position(
    tmp_path: Path, content: str, message: str
) -> None:
    path = tmp_path / "a.txt"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(FormatError, match=message):
        parse_yolo_label(path, 100, 50, NAMES)


VOC = (
    "<annotation><filename>a.jpg</filename><size><width>100</width><height>50</height><depth>3</depth></size>"
    "<object><name>short</name><bndbox><xmin>10</xmin><ymin>5</ymin><xmax>30</xmax><ymax>15</ymax></bndbox></object>"
    "</annotation>"
)


def test_voc_is_parsed(tmp_path: Path) -> None:
    path = tmp_path / "a.xml"
    path.write_text(VOC, encoding="utf-8")
    voc = parse_voc(path)
    assert (voc.filename, voc.width, voc.height) == ("a.jpg", 100, 50)
    assert [(b.label, b.xyxy) for b in voc.boxes] == [("short", (10.0, 5.0, 30.0, 15.0))]


def test_a_file_of_nul_bytes_is_reported_as_such(tmp_path: Path) -> None:
    path = tmp_path / "a.xml"
    path.write_bytes(b"\x00" * 249)
    with pytest.raises(FormatError, match="NUL bytes"):
        parse_voc(path)


def test_an_empty_voc_file_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "a.xml"
    path.write_bytes(b"")
    with pytest.raises(FormatError, match="empty"):
        parse_voc(path)


@pytest.mark.parametrize(
    ("xml", "message"),
    [
        ("<annotation><object>", "not well-formed"),
        ("<annotation><object><name>x</name></object></annotation>", "no name or no bndbox"),
        (
            "<annotation><object><name>x</name><bndbox><xmin>a</xmin><ymin>1</ymin><xmax>2</xmax><ymax>3</ymax></bndbox></object></annotation>",
            "non-numeric",
        ),
        (
            "<annotation><object><name>x</name><bndbox><xmin>1</xmin><ymin>1</ymin><xmax>2</xmax></bndbox></object></annotation>",
            "incomplete",
        ),
    ],
)
def test_malformed_voc_is_reported(tmp_path: Path, xml: str, message: str) -> None:
    path = tmp_path / "a.xml"
    path.write_text(xml, encoding="utf-8")
    with pytest.raises(FormatError, match=message):
        parse_voc(path)


def test_voc_refuses_entity_tricks(tmp_path: Path) -> None:
    path = tmp_path / "a.xml"
    path.write_text(
        '<?xml version="1.0"?><!DOCTYPE a [<!ENTITY x SYSTEM "file:///etc/passwd">]><annotation>&x;</annotation>',
        encoding="utf-8",
    )
    with pytest.raises(FormatError, match="not well-formed"):
        parse_voc(path)
