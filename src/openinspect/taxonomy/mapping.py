"""The taxonomy applied to the annotation records: a normalized label next to each original one.

Nothing here rewrites a record. Every box keeps its ``original_label``; the mapping adds
``normalized_label``, ``mapping_status`` and the evidence, and decides per image whether the image
can enter a cross-source release. The code sees generic fields only (source id, image id, the keys
``group_id``, ``subgroup_id`` and ``acquisition_id``, the split); what a label means is in the
configuration.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from openinspect.dedup.inventory import ImageItem, InventoryError, load_items
from openinspect.ingest.layout import source_dirs
from openinspect.provenance.records import AnnotationRecord
from openinspect.taxonomy.config import COMPARABLE, Status, Taxonomy, TaxonomyError

Eligibility = Literal["eligible", "negative", "excluded"]
ELIGIBILITY: tuple[Eligibility, ...] = ("eligible", "negative", "excluded")


@dataclass(frozen=True)
class Box:
    """One box as ingest recorded it, in pixels of the image."""

    ann_index: int
    original_label: str
    bbox: tuple[float, float, float, float]  # x_min, y_min, x_max, y_max
    in_bounds: bool

    @property
    def width(self) -> float:
        return self.bbox[2] - self.bbox[0]

    @property
    def height(self) -> float:
        return self.bbox[3] - self.bbox[1]

    @property
    def finite(self) -> bool:
        return all(math.isfinite(v) for v in self.bbox)


@dataclass(frozen=True)
class AnnotatedImage:
    item: ImageItem
    boxes: tuple[Box, ...]


@dataclass(frozen=True)
class MappedBox:
    box: Box
    normalized_label: str | None
    status: Status
    benchmark: bool  # an EXACT or COMPATIBLE mapping onto a class every source shares


@dataclass(frozen=True)
class MappedImage:
    item: ImageItem
    boxes: tuple[MappedBox, ...]
    eligibility: Eligibility
    excluded_by: tuple[str, ...]  # original labels of the boxes that keep the image out


def load_annotated(
    data_dir: Path, slugs: Sequence[str], *, acquisition: Mapping[str, str | None] | None = None
) -> list[AnnotatedImage]:
    """The decodable images of ``slugs`` with their boxes, in a fixed order."""
    items, _ = load_items(data_dir, list(slugs), acquisition=acquisition)
    boxes: dict[tuple[str, str], list[Box]] = {}
    for slug in sorted(set(slugs)):
        path = source_dirs(data_dir, slug).records / "annotations.jsonl"
        if not path.is_file():
            raise InventoryError(
                f"{slug}: no annotation records; run `openinspect ingest run {slug}`"
            )
        for line in path.read_text(encoding="utf-8").splitlines():
            record = AnnotationRecord.model_validate_json(line)
            x0, y0, x1, y1 = record.bbox_xyxy
            boxes.setdefault((slug, record.source_item_id), []).append(
                Box(record.ann_index, record.original_label, (x0, y0, x1, y1), record.in_bounds)
            )
    known = {item.key for item in items}
    orphans = sorted(key for key in boxes if key not in known)
    if orphans:
        source, item_id = orphans[0]
        raise InventoryError(
            f"{len(orphans)} annotated images have no decodable image record, e.g. {source}:{item_id}"
        )
    return [
        AnnotatedImage(item, tuple(sorted(boxes.get(item.key, []), key=lambda b: b.ann_index)))
        for item in items
    ]


def map_image(image: AnnotatedImage, taxonomy: Taxonomy, benchmark: Sequence[str]) -> MappedImage:
    """Map every box of one image and decide whether the image can enter the release (SPEC 7.4).

    An image without boxes is a negative. An image with a box whose label is not a benchmark class
    is excluded as a whole: dropping only that box would turn a real defect into background.
    """
    shared = set(benchmark)
    mapped: list[MappedBox] = []
    for box in image.boxes:
        mapping = taxonomy.mapping(image.item.source, box.original_label)
        mapped.append(
            MappedBox(
                box=box,
                normalized_label=mapping.normalized_label,
                status=mapping.status,
                benchmark=mapping.status in COMPARABLE and mapping.normalized_label in shared,
            )
        )
    excluded_by = tuple(sorted({m.box.original_label for m in mapped if not m.benchmark}))
    eligibility: Eligibility
    if not mapped:
        eligibility = "negative"
    elif excluded_by:
        eligibility = "excluded"
    else:
        eligibility = "eligible"
    return MappedImage(image.item, tuple(mapped), eligibility, excluded_by)


def map_images(images: Sequence[AnnotatedImage], taxonomy: Taxonomy) -> list[MappedImage]:
    benchmark = taxonomy.benchmark_classes
    if not benchmark:
        raise TaxonomyError("no normalized class is reached by every source: no benchmark class")
    return [map_image(image, taxonomy, benchmark) for image in images]


def used_labels(images: Sequence[AnnotatedImage]) -> dict[str, list[str]]:
    """Sorted unique labels per source, as the annotation records use them."""
    used: dict[str, set[str]] = {}
    for image in images:
        used.setdefault(image.item.source, set()).update(b.original_label for b in image.boxes)
    return {source: sorted(labels) for source, labels in sorted(used.items())}
