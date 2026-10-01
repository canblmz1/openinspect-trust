"""The machine-readable release: ``release.json``, item and box provenance, split files.

``release.json`` describes the sources, versions and licences, the taxonomy, the crop policy and
the sample, every split scheme with its method and measurements, the invariants, the M3
limitations and the unresolved human validation, the hashes of every file and the commit that
produced it. ``items.parquet`` holds one row per released image with its full provenance,
``annotations.parquet`` one row per box with original and normalized label, ``excluded.parquet``
every image or crop anchor that did not make it, with the reason.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

import pyarrow as pa
from pydantic import Field

from openinspect.files import parquet_bytes, replace_bytes, sha256_bytes
from openinspect.provenance.schema import StrictModel
from openinspect.release.checks import Invariant, SplitMeasure
from openinspect.release.config import CropPolicy, SizeRange
from openinspect.release.pool import Candidate, Exclusion

ITEMS = "items.parquet"
ANNOTATIONS = "annotations.parquet"
EXCLUDED = "excluded.parquet"
RELEASE = "release.json"
INTERPRETATION = [
    "A0 - A1 approximates the effect of leakage and split structure: the same items, split at random and split group-aware.",
    "A1 - B approximates a residual source or domain shift, not a single cause.",
    "A0 - B is not a leakage measure: between sources the acquisition hardware, the production environment, the lighting, the resolution, the annotation conventions, the source-specific taxonomy and the label distribution all change.",
    "Training-set sizes differ between schemes (a B fold trains on fewer items than A0 or A1).",
]


class ReleasedFile(StrictModel):
    """The bytes written for one item under ``<data>/release/<version>/images/``."""

    sha256: str
    sha256_pixels: str | None  # crops: hash of the decoded pixels, independent of the PNG encoder
    bytes: int = Field(ge=0)


class SourceEntry(StrictModel):
    source: str
    dataset_name: str
    version: str | None
    doi: str | None
    official_url: str | None
    licence: str
    licence_url: str | None
    attribution: str | None
    changes_must_be_indicated: bool | None
    archive_sha256: dict[str, str]
    acquisition_id: str | None
    primary_similarity_level: str
    crop_policy: CropPolicy | None
    images_ingested: int
    candidates: int
    released_images: int
    released_boxes: int
    share: float
    exclusions: dict[str, int]  # reason -> images (crop anchors for crop_* reasons)


class ClassEntry(StrictModel):
    class_id: int
    name: str
    family: str
    original_labels: dict[str, list[str]]  # source -> original labels behind the class
    statuses: dict[str, list[str]]  # source -> mapping statuses
    released_boxes: int
    released_images: int


class TaxonomyEntry(StrictModel):
    path: str
    sha256: str
    benchmark_classes: list[str]
    classes: list[ClassEntry]


class SchemeEntry(StrictModel):
    name: str
    kind: Literal["random", "group_aware", "source_held_out"]
    held_out: str | None
    method: str
    ratios: dict[str, float]
    file: str
    sha256: str
    meta_file: str
    counts: dict[str, int]
    measure: SplitMeasure


class Sampling(StrictModel):
    method: str
    max_source_share: float
    size: SizeRange
    negatives: str
    available: dict[str, int]  # candidates per source
    quotas: dict[str, int]  # released per source


class Counts(StrictModel):
    images: int
    boxes: int
    by_source: dict[str, int]
    by_class: dict[str, int]


class ValidationRecord(StrictModel):
    status: str
    queue: str
    reviewed: int
    queued: int
    limitation: str | None


class M3Limitations(StrictModel):
    human_validation: ValidationRecord
    statements: list[str]


class Generator(StrictModel):
    command: str
    code_commit: str | None
    code_dirty: bool | None
    pillow: str
    libjpeg: str | None


class ReleaseManifest(StrictModel):
    schema_version: Literal[1] = 1
    name: str = "OpenInspect-Trust"
    version: str
    seed: int
    generated_by: Generator
    config_sha256: str
    images_dir: str  # where the images are, relative to the data directory
    sources: list[SourceEntry]
    taxonomy: TaxonomyEntry
    sampling: Sampling
    counts: Counts
    canonical_split: str
    splits: list[SchemeEntry]
    interpretation: list[str]
    notes: list[str]  # facts of this build that qualify how the splits can be read
    invariants: list[Invariant]
    m3_limitations: M3Limitations
    files: dict[str, str]  # file name -> SHA-256 (items, annotations, excluded)
    inputs: dict[str, str]  # input file -> SHA-256


def _strings(values: Sequence[str | None]) -> pa.DictionaryArray:
    return pa.array(list(values), type=pa.string()).dictionary_encode()


def _crop(item: Candidate, k: int) -> int | None:
    return None if item.crop is None else item.crop[k]


def items_table(
    items: Sequence[Candidate],
    files: Sequence[ReleasedFile],
    provenance: Mapping[tuple[str, str], tuple[str, str, str]],
    versions: Mapping[str, str | None],
    similarity: Mapping[tuple[str, str], str],
    groups: Sequence[str],
    schemes: Mapping[str, Sequence[str]],
    canonical: str,
) -> pa.Table:
    """One row per released image. ``provenance`` gives (source URL, licence, original SHA-256)."""
    columns: dict[str, pa.Array] = {
        "global_id": pa.array([i.global_id for i in items], type=pa.string()),
        "source": _strings([i.source for i in items]),
        "source_item_id": pa.array([i.item.item_id for i in items], type=pa.string()),
        "source_version": _strings([versions.get(i.source) for i in items]),
        "source_url": _strings([provenance[i.item.key][0] for i in items]),
        "licence": _strings([provenance[i.item.key][1] for i in items]),
        "sha256_source": pa.array([provenance[i.item.key][2] for i in items], type=pa.string()),
        "file_name": pa.array([i.file_name for i in items], type=pa.string()),
        "sha256": pa.array([f.sha256 for f in files], type=pa.string()),
        "sha256_pixels": pa.array([f.sha256_pixels for f in files], type=pa.string()),
        "bytes": pa.array([f.bytes for f in files], type=pa.int64()),
        "width": pa.array([i.width for i in items], type=pa.int32()),
        "height": pa.array([i.height for i in items], type=pa.int32()),
        "crop_x_min": pa.array([_crop(i, 0) for i in items], type=pa.int32()),
        "crop_y_min": pa.array([_crop(i, 1) for i in items], type=pa.int32()),
        "crop_x_max": pa.array([_crop(i, 2) for i in items], type=pa.int32()),
        "crop_y_max": pa.array([_crop(i, 3) for i in items], type=pa.int32()),
        "original_split": _strings([i.item.split for i in items]),
        "canonical_split": _strings(list(schemes[canonical])),
        "group_id": _strings([i.item.group_id for i in items]),
        "subgroup_id": _strings([i.item.subgroup_id for i in items]),
        "acquisition_id": _strings([i.item.acquisition_id for i in items]),
        "similarity_group_id": _strings([similarity.get(i.item.key) for i in items]),
        "constraint_group": pa.array(list(groups), type=pa.string()),
        "original_labels": _strings(
            [";".join(sorted({b.original_label for b in i.boxes})) for i in items]
        ),
        "normalized_labels": _strings([i.signature for i in items]),
        "boxes": pa.array([len(i.boxes) for i in items], type=pa.int32()),
    }
    for name, split in schemes.items():
        columns[f"split_{name}"] = _strings(list(split))
    return pa.table(columns)


def annotations_table(items: Sequence[Candidate]) -> pa.Table:
    rows = [(item, k, b) for item in items for k, b in enumerate(item.boxes)]
    return pa.table(
        {
            "ann_id": pa.array([f"{i.global_id}#{k}" for i, k, _ in rows], type=pa.string()),
            "global_id": pa.array([i.global_id for i, _, _ in rows], type=pa.string()),
            "source": _strings([i.source for i, _, _ in rows]),
            "source_item_id": pa.array([i.item.item_id for i, _, _ in rows], type=pa.string()),
            "source_ann_index": pa.array([b.source_ann_index for _, _, b in rows], type=pa.int32()),
            "original_label": _strings([b.original_label for _, _, b in rows]),
            "normalized_label": _strings([b.normalized_label for _, _, b in rows]),
            "mapping_status": _strings([b.mapping_status for _, _, b in rows]),
            "class_id": pa.array([b.class_id for _, _, b in rows], type=pa.int8()),
            "x_min": pa.array([b.bbox[0] for _, _, b in rows], type=pa.float64()),
            "y_min": pa.array([b.bbox[1] for _, _, b in rows], type=pa.float64()),
            "x_max": pa.array([b.bbox[2] for _, _, b in rows], type=pa.float64()),
            "y_max": pa.array([b.bbox[3] for _, _, b in rows], type=pa.float64()),
            "source_x_min": pa.array([b.bbox_source[0] for _, _, b in rows], type=pa.float64()),
            "source_y_min": pa.array([b.bbox_source[1] for _, _, b in rows], type=pa.float64()),
            "source_x_max": pa.array([b.bbox_source[2] for _, _, b in rows], type=pa.float64()),
            "source_y_max": pa.array([b.bbox_source[3] for _, _, b in rows], type=pa.float64()),
        }
    )


def excluded_table(excluded: Sequence[Exclusion]) -> pa.Table:
    rows = sorted(excluded, key=lambda e: (e.source, e.source_item_id, e.reason, e.detail))
    return pa.table(
        {
            "source": _strings([e.source for e in rows]),
            "source_item_id": pa.array([e.source_item_id for e in rows], type=pa.string()),
            "reason": _strings([e.reason for e in rows]),
            "detail": pa.array([e.detail for e in rows], type=pa.string()),
        }
    )


def split_csv(items: Sequence[Candidate], split: Sequence[str]) -> bytes:
    """``id,split`` sorted by id (SPEC 6.6)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["id", "split"])
    for global_id, name in sorted(zip((i.global_id for i in items), split, strict=True)):
        writer.writerow([global_id, name])
    return buffer.getvalue().encode("utf-8")


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def write_parquet(path: Path, table: pa.Table) -> str:
    data = parquet_bytes(table)
    replace_bytes(path, data)
    return sha256_bytes(data)


def write_manifest(path: Path, manifest: ReleaseManifest) -> None:
    replace_bytes(path, (manifest.model_dump_json(indent=2) + "\n").encode("utf-8"))


def read_manifest(path: Path) -> ReleaseManifest:
    return ReleaseManifest.model_validate_json(path.read_text(encoding="utf-8"))
