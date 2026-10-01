"""Label-quality checks: suspicious annotations are flagged ``REVIEW_REQUIRED``, never corrected.

Each check is a declared rule (``label_quality`` in ``configs/taxonomy.yaml``) over generic fields:
box geometry, the ingest flags of an image, the labels of machine-detected near-duplicate pairs
from M3, and the status of a label's mapping. A flag asks a person to look; no label, box or image
is changed or dropped here.
"""

from __future__ import annotations

import csv
import io
import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from openinspect.taxonomy.config import QualityRules, Taxonomy
from openinspect.taxonomy.mapping import MappedBox, MappedImage

REVIEW_REQUIRED = "REVIEW_REQUIRED"
NEAR_CATEGORY = "NEAR_DUPLICATE"  # the M3 machine category of the near level
MAD_SCALE = 0.6745  # modified z-score: 0.6745 (x - median) / MAD (Iglewicz and Hoaglin)
SIGNALS: dict[str, tuple[str, str]] = {  # signal -> (check, what it means)
    "malformed_box": ("geometry", "a coordinate is not finite, or the box is inverted"),
    "zero_area_box": ("geometry", "the box has zero width or zero height"),
    "box_out_of_bounds": ("geometry", "the box leaves the image (recorded at ingest)"),
    "tiny_box": ("geometry", "the shorter side is below `min_box_side_px`"),
    "extreme_aspect_ratio": (
        "geometry",
        "longer side over shorter side is above `max_aspect_ratio`",
    ),
    "duplicate_box": (
        "class_consistency",
        "two boxes with the same label overlap with IoU at or above `same_box_iou`",
    ),
    "conflicting_box": (
        "class_consistency",
        "two boxes with different labels overlap with IoU at or above `same_box_iou`",
    ),
    "class_size_outlier": (
        "class_consistency",
        "the modified z-score of the log relative box area within (source, label) is beyond "
        "`size_outlier_z`",
    ),
    "source_format_disagreement": (
        "source_format",
        "an ingest flag says the source's annotation formats disagree or one cannot be read",
    ),
    "near_duplicate_label_conflict": (
        "neighbour_label",
        "a machine-detected near-duplicate pair (M3 near level and pHash at or below the M3 "
        "candidate distance, or identical bytes) whose normalized label sets differ",
    ),
    "mapping_ambiguity": (
        "mapping",
        "the label's mapping is AMBIGUOUS, so its boxes are not merged",
    ),
}
CHECKS = ("geometry", "class_consistency", "source_format", "neighbour_label", "mapping")
COLUMNS = (
    "review_id",
    "status",
    "check",
    "signal",
    "source_id",
    "image_id",
    "ann_index",
    "original_label",
    "normalized_label",
    "mapping_status",
    "related_source_id",
    "related_image_id",
    "related_ann_index",
    "related_labels",
    "measure",
    "detail",
    "human_decision",
    "human_notes",
)


@dataclass(frozen=True)
class Finding:
    """One reason to review; becomes one row of ``review-required.csv``."""

    signal: str
    source_id: str
    image_id: str = ""  # empty for a finding about a label as a whole
    ann_index: int | None = None
    original_label: str = ""
    normalized_label: str = ""
    mapping_status: str = ""
    related_source_id: str = ""
    related_image_id: str = ""
    related_ann_index: int | None = None
    related_labels: str = ""
    measure: float | None = None
    detail: str = ""

    @property
    def check(self) -> str:
        return SIGNALS[self.signal][0]

    def sort_key(self) -> tuple[int, int, str, str, int, str, str, int]:
        return (
            CHECKS.index(self.check),
            list(SIGNALS).index(self.signal),
            self.source_id,
            self.image_id,
            -1 if self.ann_index is None else self.ann_index,
            self.related_source_id,
            self.related_image_id,
            -1 if self.related_ann_index is None else self.related_ann_index,
        )


@dataclass(frozen=True)
class NeighbourPair:
    """A pair of images from the M3 similarity audit (machine-detected, not human-validated)."""

    source_a: str
    image_a: str
    source_b: str
    image_b: str
    category: str
    cosine: float
    phash_distance: int
    sha256_equal: bool


@dataclass(frozen=True)
class NeighbourAgreement:
    """How often the near-duplicate pairs of one scope carry different normalized label sets."""

    scope: str  # a source id, or "a / b" for pairs between two sources
    near_pairs: int
    near_pairs_differing: int
    strict_pairs: int  # near pairs whose pHash distance is also at or below the candidate distance
    strict_pairs_differing: int


def iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _box_finding(
    signal: str,
    image: MappedImage,
    m: MappedBox,
    *,
    measure: float | None = None,
    detail: str = "",
    related: MappedBox | None = None,
) -> Finding:
    return Finding(
        signal=signal,
        source_id=image.item.source,
        image_id=image.item.item_id,
        ann_index=m.box.ann_index,
        original_label=m.box.original_label,
        normalized_label=m.normalized_label or "",
        mapping_status=m.status,
        related_source_id="" if related is None else image.item.source,
        related_image_id="" if related is None else image.item.item_id,
        related_ann_index=None if related is None else related.box.ann_index,
        related_labels="" if related is None else related.box.original_label,
        measure=measure,
        detail=detail,
    )


def _bbox(bbox: tuple[float, float, float, float]) -> str:
    return "bbox [" + ", ".join(f"{v:.4g}" for v in bbox) + "]"


def valid_geometry(m: MappedBox) -> bool:
    return m.box.finite and m.box.width > 0 and m.box.height > 0


def geometry_findings(image: MappedImage, rules: QualityRules) -> list[Finding]:
    found: list[Finding] = []
    for m in image.boxes:
        box = m.box
        if not box.finite or box.width < 0 or box.height < 0:
            found.append(_box_finding("malformed_box", image, m, detail=_bbox(box.bbox)))
            continue
        if box.width == 0 or box.height == 0:
            found.append(
                _box_finding("zero_area_box", image, m, measure=0.0, detail=_bbox(box.bbox))
            )
            continue
        if not box.in_bounds:
            found.append(_box_finding("box_out_of_bounds", image, m, detail=_bbox(box.bbox)))
        short, long = min(box.width, box.height), max(box.width, box.height)
        if short < rules.min_box_side_px:
            found.append(
                _box_finding(
                    "tiny_box",
                    image,
                    m,
                    measure=round(short, 3),
                    detail=f"shorter side {short:g} px",
                )
            )
        ratio = long / short
        if ratio > rules.max_aspect_ratio:
            found.append(
                _box_finding(
                    "extreme_aspect_ratio",
                    image,
                    m,
                    measure=round(ratio, 2),
                    detail=f"{box.width:g} x {box.height:g} px",
                )
            )
    return found


def overlap_findings(image: MappedImage, rules: QualityRules) -> list[Finding]:
    found: list[Finding] = []
    boxes = [m for m in image.boxes if valid_geometry(m)]
    for i, a in enumerate(boxes):
        for b in boxes[i + 1 :]:
            value = iou(a.box.bbox, b.box.bbox)
            if value < rules.same_box_iou:
                continue
            same = a.box.original_label == b.box.original_label
            found.append(
                _box_finding(
                    "duplicate_box" if same else "conflicting_box",
                    image,
                    a,
                    related=b,
                    measure=round(value, 4),
                    detail=f"IoU {value:.3f} with box {b.box.ann_index} ({b.box.original_label})",
                )
            )
    return found


def size_outlier_findings(images: Sequence[MappedImage], rules: QualityRules) -> list[Finding]:
    """Boxes whose relative area is atypical for their label within their source."""
    groups: dict[tuple[str, str], list[tuple[MappedImage, MappedBox, float]]] = defaultdict(list)
    for image in images:
        width, height = image.item.width, image.item.height
        if not width or not height:
            continue
        for m in image.boxes:
            if valid_geometry(m):
                share = m.box.width * m.box.height / (width * height)
                groups[(image.item.source, m.box.original_label)].append(
                    (image, m, math.log(share))
                )
    found: list[Finding] = []
    for (_, label), members in sorted(groups.items()):
        values = np.array([v for _, _, v in members])
        median = float(np.median(values))
        mad = float(np.median(np.abs(values - median)))
        if mad == 0:
            continue
        for image, m, value in members:
            z = MAD_SCALE * (value - median) / mad
            if abs(z) > rules.size_outlier_z:
                found.append(
                    _box_finding(
                        "class_size_outlier",
                        image,
                        m,
                        measure=round(z, 2),
                        detail=f"box area {math.exp(value):.2%} of the image; the median {label} "
                        f"box covers {math.exp(median):.2%}",
                    )
                )
    return found


def _label_set(image: MappedImage) -> tuple[str, str, str]:
    """The image's original labels, normalized labels and statuses, each joined by ';'."""
    original = sorted({m.box.original_label for m in image.boxes})
    normalized = sorted({m.normalized_label or "" for m in image.boxes})
    statuses = sorted({m.status for m in image.boxes})
    return ";".join(original), ";".join(normalized), ";".join(statuses)


def format_findings(image: MappedImage, rules: QualityRules) -> list[Finding]:
    ignore = set(rules.informational_flags)
    original, normalized, statuses = _label_set(image)
    return [
        Finding(
            signal="source_format_disagreement",
            source_id=image.item.source,
            image_id=image.item.item_id,
            original_label=original,
            normalized_label=normalized,
            mapping_status=statuses,
            detail=f"ingest flag {flag}",
        )
        for flag in image.item.flags
        if flag.split(":", 1)[0].strip() not in ignore
    ]


def _normalized(image: MappedImage) -> frozenset[str]:
    return frozenset(m.normalized_label for m in image.boxes if m.normalized_label is not None)


def _scope(a: str, b: str) -> str:
    return a if a == b else " / ".join(sorted((a, b)))


def neighbour_findings(
    images: Sequence[MappedImage], pairs: Iterable[NeighbourPair], phash_max: int
) -> tuple[list[Finding], list[NeighbourAgreement]]:
    """Near-duplicate pairs whose label sets differ, and how common that is per scope.

    A strict pair is at the M3 near level and within the M3 pHash candidate distance (both
    representations call the images near-identical), or byte-identical; only strict pairs become
    findings. The agreement counts cover every near-level pair and are descriptive.
    """
    by_key = {image.item.key: image for image in images}
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    found: list[Finding] = []
    for pair in pairs:
        a = by_key.get((pair.source_a, pair.image_a))
        b = by_key.get((pair.source_b, pair.image_b))
        if a is None or b is None:
            continue
        near = pair.category == NEAR_CATEGORY or pair.sha256_equal
        if not near:
            continue
        strict = pair.sha256_equal or pair.phash_distance <= phash_max
        differ = _normalized(a) != _normalized(b)
        row = counts[_scope(pair.source_a, pair.source_b)]
        row[0] += 1
        row[1] += int(differ)
        row[2] += int(strict)
        row[3] += int(strict and differ)
        if strict and differ:
            original, normalized, statuses = _label_set(a)
            related, related_normalized, _ = _label_set(b)
            found.append(
                Finding(
                    signal="near_duplicate_label_conflict",
                    source_id=pair.source_a,
                    image_id=pair.image_a,
                    original_label=original,
                    normalized_label=normalized,
                    mapping_status=statuses,
                    related_source_id=pair.source_b,
                    related_image_id=pair.image_b,
                    related_labels=related,
                    measure=round(pair.cosine, 4),
                    detail=f"normalized labels [{normalized}] vs [{related_normalized}]; cosine "
                    f"{pair.cosine:.3f}, pHash distance {pair.phash_distance}"
                    + ("; identical bytes" if pair.sha256_equal else ""),
                )
            )
    agreement = [NeighbourAgreement(scope, *values) for scope, values in sorted(counts.items())]
    return found, agreement


def mapping_findings(images: Sequence[MappedImage], taxonomy: Taxonomy) -> list[Finding]:
    boxes: dict[tuple[str, str], int] = defaultdict(int)
    holders: dict[tuple[str, str], set[str]] = defaultdict(set)
    for image in images:
        for m in image.boxes:
            boxes[(image.item.source, m.box.original_label)] += 1
            holders[(image.item.source, m.box.original_label)].add(image.item.item_id)
    found: list[Finding] = []
    for source, labels in sorted(taxonomy.mappings.items()):
        for label, mapping in sorted(labels.items()):
            n = boxes.get((source, label), 0)
            if mapping.status != "AMBIGUOUS" or n == 0:
                continue
            found.append(
                Finding(
                    signal="mapping_ambiguity",
                    source_id=source,
                    original_label=label,
                    normalized_label=mapping.normalized_label or "",
                    mapping_status=mapping.status,
                    measure=float(n),
                    detail=f"candidate class {mapping.candidate}; {n} boxes in "
                    f"{len(holders[(source, label)])} images keep their own class (not merged)",
                )
            )
    return found


def all_findings(
    images: Sequence[MappedImage],
    taxonomy: Taxonomy,
    pairs: Iterable[NeighbourPair],
    phash_max: int,
) -> tuple[list[Finding], list[NeighbourAgreement]]:
    """Every finding in a fixed order, and the near-duplicate label agreement per scope."""
    rules = taxonomy.label_quality
    found: list[Finding] = []
    for image in images:
        found += geometry_findings(image, rules)
        found += overlap_findings(image, rules)
        found += format_findings(image, rules)
    found += size_outlier_findings(images, rules)
    neighbours, agreement = neighbour_findings(images, pairs, phash_max)
    found += neighbours
    found += mapping_findings(images, taxonomy)
    found.sort(key=Finding.sort_key)
    return found, agreement


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def review_csv(findings: Sequence[Finding]) -> bytes:
    """``review-required.csv``: one row per finding, status REVIEW_REQUIRED, decision columns empty."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(COLUMNS)
    for number, f in enumerate(findings, start=1):
        writer.writerow(
            [
                f"LQ-{number:05d}",
                REVIEW_REQUIRED,
                f.check,
                f.signal,
                f.source_id,
                f.image_id,
                _cell(f.ann_index),
                f.original_label,
                f.normalized_label,
                f.mapping_status,
                f.related_source_id,
                f.related_image_id,
                _cell(f.related_ann_index),
                f.related_labels,
                _cell(f.measure),
                f.detail,
                "",
                "",
            ]
        )
    return buffer.getvalue().encode("utf-8")


def read_pairs(path: Path) -> list[NeighbourPair]:
    """The pairs of ``artifacts/m3/duplicate-pairs.parquet``."""
    columns = (
        "source_a",
        "image_a",
        "source_b",
        "image_b",
        "category",
        "cosine",
        "phash_distance",
        "sha256_equal",
    )
    data = pq.read_table(path, columns=list(columns)).to_pydict()
    return [
        NeighbourPair(str(sa), str(ia), str(sb), str(ib), str(cat), float(cos), int(ph), bool(same))
        for sa, ia, sb, ib, cat, cos, ph, same in zip(*(data[c] for c in columns), strict=True)
    ]
