"""Synthetic positives for the near-duplicate threshold (M3D).

A synthetic positive is an image and a mildly transformed copy of it: by construction the same
content. The list below was fixed before any result was computed (docs/M3_PROTOCOL.md). Each
transform is seeded from the image hash and the transform name, so the same input always gives the
same copy.

* ``photometric`` and ``geometric`` transforms make up the near-duplicate set: re-encoding,
  resampling, brightness and contrast changes, blur, and a slightly different field of view
  (a crop that keeps at least 90% of each side).
* ``partial`` overlap (an 80% crop) is reported but is not part of the set that fixes the threshold.
"""

from __future__ import annotations

import io
import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from PIL import Image, ImageEnhance, ImageFilter

Kind = Literal["photometric", "geometric", "partial"]
Apply = Callable[[Image.Image, random.Random], Image.Image]


@dataclass(frozen=True)
class Transform:
    name: str
    kind: Kind
    near_duplicate: bool  # member of the set that fixes the near-duplicate threshold
    apply: Apply


def _jpeg(quality: int) -> Apply:
    def run(image: Image.Image, rng: random.Random) -> Image.Image:
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="JPEG", quality=quality)
        buffer.seek(0)
        with Image.open(buffer) as again:
            again.load()
            return again.convert("RGB")

    return run


def _enhance(
    enhancer: type[ImageEnhance.Brightness] | type[ImageEnhance.Contrast], factor: float
) -> Apply:
    def run(image: Image.Image, rng: random.Random) -> Image.Image:
        return enhancer(image.convert("RGB")).enhance(factor)

    return run


def _blur(image: Image.Image, rng: random.Random) -> Image.Image:
    radius = max(0.5, 0.005 * min(image.size))  # about one pixel at the 224-pixel model scale
    return image.convert("RGB").filter(ImageFilter.GaussianBlur(radius=radius))


def _resample(image: Image.Image, rng: random.Random) -> Image.Image:
    width, height = image.size
    small = image.convert("RGB").resize(
        (max(1, width // 2), max(1, height // 2)), Image.Resampling.BILINEAR
    )
    return small.resize((width, height), Image.Resampling.BICUBIC)


def _crop(fraction: float) -> Apply:
    def run(image: Image.Image, rng: random.Random) -> Image.Image:
        width, height = image.size
        crop_w, crop_h = max(1, round(width * fraction)), max(1, round(height * fraction))
        left = rng.randint(0, width - crop_w)
        top = rng.randint(0, height - crop_h)
        return image.convert("RGB").crop((left, top, left + crop_w, top + crop_h))

    return run


TRANSFORMS: tuple[Transform, ...] = (
    Transform("jpeg_q75", "photometric", True, _jpeg(75)),
    Transform("jpeg_q40", "photometric", True, _jpeg(40)),
    Transform("brightness_up", "photometric", True, _enhance(ImageEnhance.Brightness, 1.15)),
    Transform("brightness_down", "photometric", True, _enhance(ImageEnhance.Brightness, 0.85)),
    Transform("contrast_up", "photometric", True, _enhance(ImageEnhance.Contrast, 1.15)),
    Transform("contrast_down", "photometric", True, _enhance(ImageEnhance.Contrast, 0.85)),
    Transform("blur", "photometric", True, _blur),
    Transform("resample_half", "photometric", True, _resample),
    Transform("crop_95", "geometric", True, _crop(0.95)),
    Transform("crop_90", "geometric", True, _crop(0.90)),
    Transform("crop_80", "partial", False, _crop(0.80)),
)
BY_NAME = {transform.name: transform for transform in TRANSFORMS}
