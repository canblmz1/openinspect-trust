"""ROI crops for sources whose images are too large or mix classes (decision D7, frozen in T32).

For every benchmark-class box (the anchor), in box order, a square crop of at least
``min_side_px`` native pixels is centred on it and shifted inside the image; a box larger than
``(1 - 2 * margin)`` of that side gets a larger crop. Pixels are never resized. A crop is kept only
if it overlaps no crop kept before (no shared pixels, so crops of one image are not near-copies
of each other), cuts no box (a truncated defect is neither present nor absent), and contains only
benchmark-class boxes (the whole-image rule of SPEC 7.4, applied to the crop). An anchor that lies
inside a crop kept earlier is covered by it. Every other anchor is recorded with its reason.
"""

from __future__ import annotations

import hashlib
import io
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from openinspect.release.config import CropPolicy
from openinspect.taxonomy.mapping import MappedBox

Rect = tuple[int, int, int, int]
REASONS = ("too_large", "overlaps_crop", "cuts_box", "other_class_inside", "invalid_box")


@dataclass(frozen=True)
class CropPlan:
    rect: Rect  # x_min, y_min, x_max, y_max in parent pixels
    anchor: int  # ann_index of the box the crop was centred on
    boxes: tuple[int, ...]  # ann_index of every parent box inside the crop


@dataclass(frozen=True)
class CropOutcome:
    plans: tuple[CropPlan, ...]
    covered: tuple[int, ...]  # anchors already inside an earlier crop
    rejected: tuple[tuple[int, str], ...]  # (anchor, reason)


def _valid(m: MappedBox) -> bool:
    return m.box.finite and m.box.width > 0 and m.box.height > 0


def _intersects(box: tuple[float, float, float, float], rect: Rect) -> bool:
    return box[0] < rect[2] and rect[0] < box[2] and box[1] < rect[3] and rect[1] < box[3]


def _inside(box: tuple[float, float, float, float], rect: Rect) -> bool:
    return rect[0] <= box[0] and rect[1] <= box[1] and box[2] <= rect[2] and box[3] <= rect[3]


def _overlap(a: Rect, b: Rect) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def crop_rect(
    box: tuple[float, float, float, float], width: int, height: int, policy: CropPolicy
) -> Rect | None:
    """The crop for one anchor box, or ``None`` when it cannot fit in the image."""
    long_side = max(box[2] - box[0], box[3] - box[1])
    side = max(policy.min_side_px, math.ceil(long_side / (1 - 2 * policy.margin)))
    if side > width or side > height:
        return None
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    x0 = min(max(round(cx - side / 2), 0), width - side)
    y0 = min(max(round(cy - side / 2), 0), height - side)
    return (x0, y0, x0 + side, y0 + side)


def plan_crops(
    width: int, height: int, boxes: Sequence[MappedBox], policy: CropPolicy
) -> CropOutcome:
    """Crops for one image, in anchor order; a pure function of the boxes and the policy."""
    plans: list[CropPlan] = []
    covered: list[int] = []
    rejected: list[tuple[int, str]] = []
    ordered = sorted(boxes, key=lambda m: m.box.ann_index)
    for anchor in ordered:
        if not anchor.benchmark:
            continue
        index = anchor.box.ann_index
        if not _valid(anchor):
            rejected.append((index, "invalid_box"))
            continue
        if any(_inside(anchor.box.bbox, p.rect) for p in plans):
            covered.append(index)
            continue
        rect = crop_rect(anchor.box.bbox, width, height, policy)
        if rect is None:
            rejected.append((index, "too_large"))
            continue
        if any(_overlap(rect, p.rect) for p in plans):
            rejected.append((index, "overlaps_crop"))
            continue
        reason = None
        inside: list[int] = []
        for m in ordered:
            if not m.box.finite:
                reason = "invalid_box"  # where it lies cannot be told
                break
            if not _intersects(m.box.bbox, rect):
                continue
            if not _valid(m):
                reason = "invalid_box"
            elif not _inside(m.box.bbox, rect):
                reason = "cuts_box"
            elif not m.benchmark:
                reason = "other_class_inside"
            if reason:
                break
            inside.append(m.box.ann_index)
        if reason:
            rejected.append((index, reason))
            continue
        plans.append(CropPlan(rect=rect, anchor=index, boxes=tuple(inside)))
    return CropOutcome(tuple(plans), tuple(covered), tuple(rejected))


def shift(box: tuple[float, float, float, float], rect: Rect) -> tuple[float, float, float, float]:
    """A parent box in the pixels of the crop ``rect``."""
    return (box[0] - rect[0], box[1] - rect[1], box[2] - rect[0], box[3] - rect[1])


def crop_png(image: Image.Image, rect: Rect) -> tuple[bytes, str]:
    """The crop of an opened image as PNG bytes, and the SHA-256 of its decoded pixels.

    The pixel hash covers mode, size and data, so it does not depend on the PNG encoder.
    """
    crop = image.crop(rect)
    buffer = io.BytesIO()
    crop.save(buffer, format="PNG", compress_level=6)
    pixels = hashlib.sha256(
        f"{crop.mode}:{crop.width}x{crop.height}:".encode() + crop.tobytes()
    ).hexdigest()
    return buffer.getvalue(), pixels


def open_image(path: Path) -> Image.Image:
    with Image.open(path) as image:
        image.load()
        return image.copy()
