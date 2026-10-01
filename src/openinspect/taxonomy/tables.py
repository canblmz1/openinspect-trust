"""The M4 artifacts: ``taxonomy-map.parquet``, ``review-required.csv`` and ``audit.json``.

One row of the map per box, keyed by generic fields, with the original label next to the
normalized one. Rows are in a fixed order and files are written atomically, so the same inputs
give the same bytes.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pyarrow as pa

from openinspect.files import parquet_bytes, replace_bytes, sha256_file
from openinspect.taxonomy.audit import M4Audit
from openinspect.taxonomy.config import Taxonomy
from openinspect.taxonomy.mapping import MappedImage
from openinspect.taxonomy.quality import Finding, review_csv

MAP = "taxonomy-map.parquet"
REVIEW = "review-required.csv"
AUDIT = "audit.json"
MAP_COLUMNS = (
    "source_id",
    "image_id",
    "ann_index",
    "group_id",
    "subgroup_id",
    "acquisition_id",
    "split",
    "original_label",
    "normalized_label",
    "mapping_status",
    "family",
    "benchmark_class",
    "evidence",
    "x_min",
    "y_min",
    "x_max",
    "y_max",
    "image_width",
    "image_height",
    "in_bounds",
    "image_eligibility",
)


def _strings(values: Sequence[str | None]) -> pa.DictionaryArray:
    return pa.array(list(values), type=pa.string()).dictionary_encode()


def map_table(images: Sequence[MappedImage], taxonomy: Taxonomy) -> pa.Table:
    """One row per box, in (source, image, box) order; images without boxes have no row."""
    rows = [
        (image, m)
        for image in sorted(images, key=lambda i: i.item.key)
        for m in sorted(image.boxes, key=lambda b: b.box.ann_index)
    ]
    evidence = [taxonomy.mapping(i.item.source, m.box.original_label).evidence for i, m in rows]
    family = [
        None if m.normalized_label is None else taxonomy.classes[m.normalized_label].family
        for _, m in rows
    ]
    columns: dict[str, pa.Array] = {
        "source_id": _strings([i.item.source for i, _ in rows]),
        "image_id": _strings([i.item.item_id for i, _ in rows]),
        "ann_index": pa.array([m.box.ann_index for _, m in rows], type=pa.int32()),
        "group_id": _strings([i.item.group_id for i, _ in rows]),
        "subgroup_id": _strings([i.item.subgroup_id for i, _ in rows]),
        "acquisition_id": _strings([i.item.acquisition_id for i, _ in rows]),
        "split": _strings([i.item.split for i, _ in rows]),
        "original_label": _strings([m.box.original_label for _, m in rows]),
        "normalized_label": _strings([m.normalized_label for _, m in rows]),
        "mapping_status": _strings([m.status for _, m in rows]),
        "family": _strings(family),
        "benchmark_class": pa.array([m.benchmark for _, m in rows], type=pa.bool_()),
        "evidence": _strings(evidence),
        "x_min": pa.array([m.box.bbox[0] for _, m in rows], type=pa.float64()),
        "y_min": pa.array([m.box.bbox[1] for _, m in rows], type=pa.float64()),
        "x_max": pa.array([m.box.bbox[2] for _, m in rows], type=pa.float64()),
        "y_max": pa.array([m.box.bbox[3] for _, m in rows], type=pa.float64()),
        "image_width": pa.array([i.item.width for i, _ in rows], type=pa.int32()),
        "image_height": pa.array([i.item.height for i, _ in rows], type=pa.int32()),
        "in_bounds": pa.array([m.box.in_bounds for _, m in rows], type=pa.bool_()),
        "image_eligibility": _strings([i.eligibility for i, _ in rows]),
    }
    return pa.table({name: columns[name] for name in MAP_COLUMNS})


def write_artifacts(
    out: Path, images: Sequence[MappedImage], taxonomy: Taxonomy, findings: Sequence[Finding]
) -> dict[str, str]:
    """Write the map and the review queue; returns file name -> SHA-256."""
    replace_bytes(out / MAP, parquet_bytes(map_table(images, taxonomy)))
    replace_bytes(out / REVIEW, review_csv(findings))
    return {name: sha256_file(out / name) for name in (MAP, REVIEW)}


def write_audit(path: Path, audit: M4Audit) -> None:
    replace_bytes(path, (audit.model_dump_json(indent=2) + "\n").encode("utf-8"))


def read_audit(path: Path) -> M4Audit:
    return M4Audit.model_validate_json(path.read_text(encoding="utf-8"))
