"""Readers for the annotation formats the sources ship: COCO JSON, YOLO txt, Pascal VOC XML.

Readers never guess: a value that is missing or malformed raises :class:`FormatError` with the file
and the reason, and the adapter turns that into an anomaly instead of inventing data.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET  # only for the ParseError type; parsing uses defusedxml
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import defusedxml.ElementTree as DefusedET
from defusedxml.common import DefusedXmlException


class FormatError(Exception):
    """A file does not follow the format it claims to follow."""


@dataclass(frozen=True)
class Box:
    label: str
    label_id: int | None
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def xyxy(self) -> tuple[float, float, float, float]:
        return (self.x0, self.y0, self.x1, self.y1)


@dataclass(frozen=True)
class CocoImage:
    id: int
    file_name: str
    width: int
    height: int
    extra_name: str | None


@dataclass
class CocoData:
    images: list[CocoImage]
    boxes: dict[int, list[Box]]  # image id -> boxes
    categories: dict[int, str]
    orphan_annotations: int  # annotations that point to an image id the file does not list
    unknown_category_annotations: int
    annotation_count: int
    licences: list[dict[str, Any]] = field(default_factory=list)
    category_annotation_counts: dict[int, int] = field(default_factory=dict)


def _require_list(data: dict[str, Any], key: str, path: Path) -> list[Any]:
    value = data.get(key)
    if not isinstance(value, list):
        raise FormatError(f"{path.name}: '{key}' is missing or not a list")
    return value


def load_coco(path: Path) -> CocoData:
    """Read a COCO detection file; boxes are converted from ``xywh`` to pixel ``xyxy``."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FormatError(f"{path.name}: cannot read JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise FormatError(f"{path.name}: the top level is not an object")
    categories = {}
    for cat in _require_list(data, "categories", path):
        categories[int(cat["id"])] = str(cat["name"])
    images: list[CocoImage] = []
    for img in _require_list(data, "images", path):
        extra = img.get("extra") if isinstance(img.get("extra"), dict) else {}
        images.append(
            CocoImage(
                id=int(img["id"]),
                file_name=str(img["file_name"]),
                width=int(img["width"]),
                height=int(img["height"]),
                extra_name=str(extra["name"]) if extra and extra.get("name") else None,
            )
        )
    image_ids = {i.id for i in images}
    boxes: dict[int, list[Box]] = {}
    orphan = unknown = 0
    per_category: dict[int, int] = {}
    annotations = _require_list(data, "annotations", path)
    for ann in annotations:
        image_id, cat_id = int(ann["image_id"]), int(ann["category_id"])
        per_category[cat_id] = per_category.get(cat_id, 0) + 1
        if image_id not in image_ids:
            orphan += 1
            continue
        if cat_id not in categories:
            unknown += 1
            continue
        x, y, w, h = (float(v) for v in ann["bbox"])
        boxes.setdefault(image_id, []).append(Box(categories[cat_id], cat_id, x, y, x + w, y + h))
    raw_licences = data.get("licenses")
    licences = (
        [dict(entry) for entry in raw_licences if isinstance(entry, dict)]
        if isinstance(raw_licences, list)
        else []
    )
    return CocoData(
        images=images,
        boxes=boxes,
        categories=categories,
        orphan_annotations=orphan,
        unknown_category_annotations=unknown,
        annotation_count=len(annotations),
        licences=licences,
        category_annotation_counts=per_category,
    )


def parse_yolo_label(path: Path, width: int, height: int, names: Sequence[str]) -> list[Box]:
    """Read a YOLO label file: ``class x_center y_center w h``, normalised. Empty file = no boxes."""
    boxes: list[Box] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 5:
            raise FormatError(f"{path.name}:{number}: expected 5 values, found {len(parts)}")
        try:
            class_id = int(parts[0])
            xc, yc, w, h = (float(v) for v in parts[1:])
        except ValueError as exc:
            raise FormatError(f"{path.name}:{number}: non-numeric value") from exc
        if not 0 <= class_id < len(names):
            raise FormatError(
                f"{path.name}:{number}: class id {class_id} outside 0..{len(names) - 1}"
            )
        half_w, half_h = w * width / 2, h * height / 2
        cx, cy = xc * width, yc * height
        boxes.append(
            Box(names[class_id], class_id, cx - half_w, cy - half_h, cx + half_w, cy + half_h)
        )
    return boxes


@dataclass(frozen=True)
class VocData:
    filename: str | None
    width: int | None
    height: int | None
    boxes: list[Box]


def parse_voc(path: Path) -> VocData:
    """Read a Pascal VOC annotation with a parser that refuses entity and DTD tricks."""
    raw = path.read_bytes()
    if not raw.strip(b"\x00"):
        raise FormatError(f"{path.name}: the file is empty or consists only of NUL bytes")
    try:
        root = DefusedET.fromstring(raw)
    except (ET.ParseError, DefusedXmlException) as exc:
        raise FormatError(f"{path.name}: not well-formed XML ({exc})") from exc
    size = root.find("size")
    width = height = None
    if size is not None:
        width = int(size.findtext("width", "0")) or None
        height = int(size.findtext("height", "0")) or None
    boxes: list[Box] = []
    for obj in root.findall("object"):
        name = obj.findtext("name")
        bndbox = obj.find("bndbox")
        if not name or bndbox is None:
            raise FormatError(f"{path.name}: an object has no name or no bndbox")
        try:
            x0, y0, x1, y1 = (
                float(bndbox.findtext(tag, "nan")) for tag in ("xmin", "ymin", "xmax", "ymax")
            )
        except ValueError as exc:
            raise FormatError(f"{path.name}: non-numeric bndbox value") from exc
        if any(v != v for v in (x0, y0, x1, y1)):  # NaN: a tag was missing
            raise FormatError(f"{path.name}: bndbox is incomplete")
        boxes.append(Box(name, None, x0, y0, x1, y1))
    return VocData(root.findtext("filename"), width, height, boxes)
