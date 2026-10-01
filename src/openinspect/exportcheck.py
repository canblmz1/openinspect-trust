"""An independent check of a YOLO detection package (M5.5, P1-4).

Independence rule: this module imports nothing from ``openinspect`` (a test enforces it). It reads
a ZIP the way a YOLO trainer would, from the archive alone: ``data.yaml``, ``images/<split>/``,
``labels/<split>/<stem>.txt``, one ``class x_center y_center width height`` row per box,
normalized to the image. It shares no code with the exporter that wrote the package, so an error
in the exporter cannot hide behind the same error in the check.

A package passes when every image decodes and has a label file, every label file has an image,
every row has five finite fields, the class id is an integer inside ``0 .. nc - 1``, the centre
and size lie in ``[0, 1]``, width and height are positive, the box rebuilt from them leaves the
image by at most half a pixel, and every class of ``data.yaml`` occurs at least once.

Half a pixel is the box rule of the ingest contract (M2: a box is in bounds when its edges lie
within half a pixel of the image), stated here, not imported. A box that leaves the image by more
than the rounding of the label file but within half a pixel passes and is counted as an
*overhang*, with the largest one, so that the report shows it.
"""

from __future__ import annotations

import hashlib
import io
import math
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import yaml
from PIL import Image, UnidentifiedImageError

IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"})
TOLERANCE = 1e-6  # rounding of six decimals in the label files
EDGE_TOLERANCE_PX = 0.5  # the box rule of the ingest contract (see the module docstring)
MAX_PROBLEMS = 50


@dataclass
class Validation:
    archive_sha256: str
    names: list[str]
    images: dict[str, int] = field(default_factory=dict)  # split -> images
    boxes: dict[str, int] = field(default_factory=dict)  # class name -> boxes
    rows: int = 0
    empty_label_files: int = 0
    overhangs: int = 0  # boxes leaving the image by more than the rounding, within half a pixel
    max_overhang_px: float = 0.0
    problems: Counter[str] = field(default_factory=Counter)
    examples: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def fail(self, kind: str, where: str) -> None:
        self.problems[kind] += 1
        if len(self.examples) < MAX_PROBLEMS:
            self.examples.append(f"{kind}: {where}")


def _names(raw: object) -> list[str]:
    if isinstance(raw, dict):
        return [str(raw[k]) for k in sorted(raw, key=int)]
    if isinstance(raw, list):
        return [str(x) for x in raw]
    return []


def validate_archive(data: bytes) -> Validation:
    archive = zipfile.ZipFile(io.BytesIO(data))
    members = [n for n in archive.namelist() if not n.endswith("/")]
    try:
        config = yaml.safe_load(archive.read("data.yaml").decode("utf-8")) or {}
    except (KeyError, yaml.YAMLError, UnicodeDecodeError):
        config = {}
    names = _names(config.get("names"))
    result = Validation(hashlib.sha256(data).hexdigest(), names)
    if not names or config.get("nc") != len(names):
        result.fail("data_yaml", "names and nc are missing or disagree")
    images: dict[tuple[str, str], str] = {}
    labels: dict[tuple[str, str], str] = {}
    for name in members:
        parts = PurePosixPath(name).parts
        if len(parts) != 3 or parts[0] not in ("images", "labels"):
            continue
        split, stem, suffix = parts[1], PurePosixPath(parts[2]).stem, PurePosixPath(parts[2]).suffix
        if parts[0] == "images" and suffix.lower() in IMAGE_SUFFIXES:
            images[(split, stem)] = name
        elif parts[0] == "labels" and suffix == ".txt":
            labels[(split, stem)] = name
    for key in sorted(set(labels) - set(images)):
        result.fail("label_without_image", labels[key])
    per_split: Counter[str] = Counter()
    per_class: Counter[int] = Counter()
    for key in sorted(images):
        split, _ = key
        per_split[split] += 1
        try:
            with Image.open(io.BytesIO(archive.read(images[key]))) as opened:
                opened.load()
                width, height = opened.size
        except (OSError, SyntaxError, ValueError, UnidentifiedImageError) as exc:
            result.fail("image_unreadable", f"{images[key]} ({type(exc).__name__})")
            continue
        if key not in labels:
            result.fail("image_without_label", images[key])
            continue
        text = archive.read(labels[key]).decode("utf-8", errors="replace")
        lines = [line for line in text.splitlines() if line.strip()]
        if not lines:
            result.empty_label_files += 1
        for number, line in enumerate(lines, start=1):
            result.rows += 1
            where = f"{labels[key]}:{number}"
            fields = line.split()
            if len(fields) != 5:
                result.fail("row_not_five_fields", where)
                continue
            try:
                class_float = float(fields[0])
                x, y, w, h = (float(v) for v in fields[1:])
            except ValueError:
                result.fail("row_not_numeric", where)
                continue
            if not all(math.isfinite(v) for v in (class_float, x, y, w, h)):
                result.fail("row_not_finite", where)
                continue
            if class_float != int(class_float) or not 0 <= int(class_float) < len(names):
                result.fail("class_id_invalid", where)
                continue
            if not all(-TOLERANCE <= v <= 1 + TOLERANCE for v in (x, y, w, h)):
                result.fail("coordinate_outside_unit_range", where)
                continue
            if w <= 0 or h <= 0:
                result.fail("box_not_positive", where)
                continue
            left, right = (x - w / 2) * width, (x + w / 2) * width
            top, bottom = (y - h / 2) * height, (y + h / 2) * height
            overhang = max(-left, -top, right - width, bottom - height, 0.0)
            rounding = TOLERANCE * max(width, height)
            if overhang > EDGE_TOLERANCE_PX + rounding:
                result.fail("box_outside_image", where)
                continue
            if overhang > rounding:
                result.overhangs += 1
                result.max_overhang_px = max(result.max_overhang_px, overhang)
            per_class[int(class_float)] += 1
    result.images = dict(sorted(per_split.items()))
    result.boxes = {names[k]: per_class[k] for k in range(len(names))}
    for k, name in enumerate(names):
        if per_class[k] == 0:
            result.fail("class_never_used", name)
    return result


def validate_file(path: Path) -> Validation:
    return validate_archive(path.read_bytes())
