"""Label-quality checks flag suspicious annotations as REVIEW_REQUIRED and never change them."""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Sequence
from pathlib import Path

import pytest

from openinspect.taxonomy.config import QualityRules
from openinspect.taxonomy.quality import (
    COLUMNS,
    Finding,
    NeighbourPair,
    all_findings,
    format_findings,
    geometry_findings,
    iou,
    mapping_findings,
    neighbour_findings,
    overlap_findings,
    read_pairs,
    review_csv,
    size_outlier_findings,
)
from tests.taxonomy_helpers import box, mapped, taxonomy, write_m3

RULES = QualityRules()


def signals(findings: Sequence[Finding]) -> list[str]:
    return [f.signal for f in findings]


def test_iou() -> None:
    assert iou((0, 0, 2, 2), (0, 0, 2, 2)) == 1.0
    assert iou((0, 0, 2, 2), (1, 0, 3, 2)) == pytest.approx(1 / 3)
    assert iou((0, 0, 1, 1), (2, 2, 3, 3)) == 0.0
    assert iou((0, 0, 0, 0), (0, 0, 0, 0)) == 0.0


def test_geometry_signals() -> None:
    image = mapped(
        "src-a",
        "g.png",
        [
            box(0, "SH", (math.nan, 0, 5, 5)),
            box(1, "SH", (5, 5, 2, 9)),  # inverted
            box(2, "SH", (3, 3, 3, 9)),  # zero width
            box(3, "SH", (90, 90, 120, 99), in_bounds=False),
            box(4, "SH", (10, 10, 11.5, 20)),  # 1.5 px wide
            box(5, "SH", (10, 10, 13, 80)),  # 3 x 70: aspect 23.3
            box(6, "SH", (40, 40, 60, 60)),  # fine
        ],
    )
    found = geometry_findings(image, RULES)
    assert [(f.signal, f.ann_index) for f in found] == [
        ("malformed_box", 0),
        ("malformed_box", 1),
        ("zero_area_box", 2),
        ("box_out_of_bounds", 3),
        ("tiny_box", 4),
        ("extreme_aspect_ratio", 5),
    ]
    assert found[4].measure == pytest.approx(1.5)
    assert found[5].measure == pytest.approx(23.33)
    assert found[0].original_label == "SH"
    assert found[0].normalized_label == "short"


def test_overlapping_boxes_are_duplicates_or_conflicts() -> None:
    image = mapped(
        "src-a",
        "o.png",
        [
            box(0, "SH", (10, 10, 30, 30)),
            box(1, "SH", (10, 10, 30, 30.5)),
            box(2, "OP", (10.2, 10, 30, 30)),
            box(3, "OP", (50, 50, 60, 60)),
            box(4, "OP", (1, 1, 1, 9)),  # zero area: ignored here
        ],
    )
    found = overlap_findings(image, RULES)
    assert [(f.signal, f.ann_index, f.related_ann_index) for f in found] == [
        ("duplicate_box", 0, 1),
        ("conflicting_box", 0, 2),
        ("conflicting_box", 1, 2),
    ]
    assert found[1].related_labels == "OP"
    assert found[1].related_image_id == "o.png"


def test_size_outliers_within_source_and_label() -> None:
    images = [
        mapped("src-a", f"s{k}.png", [box(0, "SH", (0, 0, 10 + k % 3, 10))]) for k in range(12)
    ]
    images.append(mapped("src-a", "big.png", [box(0, "SH", (0, 0, 95, 95))]))
    images.append(mapped("src-a", "z.png", [box(0, "SH", (0, 0, 0, 5))]))  # invalid: skipped
    images.append(mapped("src-b", "same.png", [box(0, "short", (0, 0, 10, 10))]))
    images.append(mapped("src-b", "same2.png", [box(0, "short", (0, 0, 10, 10))]))  # MAD 0
    images.append(mapped("src-b", "nosize.png", [box(0, "short", (0, 0, 10, 10))], size=(0, 0)))
    found = size_outlier_findings(images, RULES)
    assert [(f.image_id, f.signal) for f in found] == [("big.png", "class_size_outlier")]
    assert found[0].measure is not None
    assert found[0].measure > RULES.size_outlier_z
    assert "the median SH box covers" in found[0].detail


def test_ingest_flags_are_format_findings_unless_informational() -> None:
    image = mapped(
        "src-b",
        "f.png",
        [box(0, "short", (1, 1, 5, 5)), box(1, "open", (6, 6, 9, 9))],
        flags=("no_annotations", "coco_missing_box: 1 box", "voc_unreadable"),
    )
    found = format_findings(image, RULES)
    assert [f.detail for f in found] == [
        "ingest flag coco_missing_box: 1 box",
        "ingest flag voc_unreadable",
    ]
    assert found[0].original_label == "open;short"
    assert found[0].normalized_label == "open;short"


def test_near_duplicate_label_conflicts_need_both_representations() -> None:
    a = mapped("src-a", "a.png", [box(0, "SH", (1, 1, 5, 5))])
    b = mapped("src-a", "b.png", [box(0, "OP", (1, 1, 5, 5))])
    c = mapped("src-a", "c.png", [box(0, "SH", (1, 1, 5, 5))])
    d = mapped("src-b", "d.png", [box(0, "short", (1, 1, 5, 5))])
    pairs = [
        NeighbourPair("src-a", "a.png", "src-a", "b.png", "NEAR_DUPLICATE", 0.97, 2, False),
        NeighbourPair("src-a", "a.png", "src-a", "c.png", "NEAR_DUPLICATE", 0.99, 0, False),
        NeighbourPair("src-a", "b.png", "src-a", "c.png", "NEAR_DUPLICATE", 0.96, 9, False),
        NeighbourPair("src-a", "a.png", "src-b", "d.png", "SAME_FAMILY_OR_SCENE", 0.93, 1, False),
        NeighbourPair("src-a", "b.png", "src-b", "d.png", "REVIEW_REQUIRED", 0.5, 30, True),
        NeighbourPair("src-a", "a.png", "src-x", "gone.png", "NEAR_DUPLICATE", 0.99, 0, False),
    ]
    found, agreement = neighbour_findings([a, b, c, d], pairs, phash_max=4)
    assert [(f.image_id, f.related_image_id) for f in found] == [
        ("a.png", "b.png"),
        ("b.png", "d.png"),  # identical bytes count as near-identical
    ]
    assert "identical bytes" in found[1].detail
    assert found[0].related_labels == "OP"
    rows = {r.scope: r for r in agreement}
    assert (rows["src-a"].near_pairs, rows["src-a"].near_pairs_differing) == (3, 2)
    assert (rows["src-a"].strict_pairs, rows["src-a"].strict_pairs_differing) == (2, 1)
    assert rows["src-a / src-b"].near_pairs == 1


def test_ambiguous_mappings_with_boxes_are_findings() -> None:
    t = taxonomy()
    images = [
        mapped("src-b", "b1.png", [box(0, "burr", (1, 1, 5, 5)), box(1, "burr", (6, 6, 9, 9))]),
        mapped("src-b", "b2.png", [box(0, "burr", (1, 1, 5, 5))]),
    ]
    found = mapping_findings(images, t)
    assert len(found) == 1
    assert found[0].measure == 3.0
    assert "candidate class spur; 3 boxes in 2 images" in found[0].detail
    assert mapping_findings([], t) == []  # no boxes, nothing to review


def test_the_review_queue_is_sorted_and_never_decides(tmp_path: Path) -> None:
    t = taxonomy()
    images = [
        mapped("src-b", "z.png", [box(0, "burr", (1, 1, 2.5, 9))]),
        mapped("src-a", "a.png", [box(0, "SH", (1, 1, 1, 9))], flags=("coco_missing_box",)),
    ]
    findings, _ = all_findings(images, t, [], phash_max=4)
    assert signals(findings) == [
        "zero_area_box",
        "tiny_box",
        "source_format_disagreement",
        "mapping_ambiguity",
    ]
    rows = list(csv.DictReader(io.StringIO(review_csv(findings).decode("utf-8"))))
    assert tuple(rows[0]) == COLUMNS
    assert [r["review_id"] for r in rows] == ["LQ-00001", "LQ-00002", "LQ-00003", "LQ-00004"]
    assert {r["status"] for r in rows} == {"REVIEW_REQUIRED"}
    assert {r["human_decision"] for r in rows} == {""} == {r["human_notes"] for r in rows}
    assert rows[1]["measure"] == "1.5"
    assert rows[3]["image_id"] == ""
    assert rows[3]["ann_index"] == ""


def test_read_pairs(tmp_path: Path) -> None:
    write_m3(
        tmp_path,
        [{"source_a": "s", "image_a": "a", "source_b": "s", "image_b": "b", "same": True}],
    )
    (pair,) = read_pairs(tmp_path / "artifacts" / "m3" / "duplicate-pairs.parquet")
    assert (pair.source_a, pair.image_a, pair.source_b, pair.image_b) == ("s", "a", "s", "b")
    assert (pair.category, pair.phash_distance, pair.sha256_equal) == ("NEAR_DUPLICATE", 2, True)
    assert pair.cosine == pytest.approx(0.97)
