"""Decode checks and metadata for image files.

Every image is decoded completely: a file that opens but is truncated is still a broken file.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

# PCB-Defect scans reach about 31 megapixels; anything far beyond is treated as a decompression bomb.
Image.MAX_IMAGE_PIXELS = 200_000_000

EXIF_ORIENTATION = 0x0112


@dataclass(frozen=True)
class ImageInfo:
    ok: bool
    width: int | None = None
    height: int | None = None
    format: str | None = None
    mode: str | None = None
    exif_orientation: int | None = None
    dhash: str | None = None
    thumbnail: bytes | None = None  # square grayscale bytes, only when requested
    error: str | None = None


def dhash64(image: Image.Image) -> str:
    """64-bit difference hash (9x8 grayscale, left pixel brighter than right), as 16 hex digits."""
    pixels = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS).tobytes()
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | (1 if pixels[row * 9 + col] > pixels[row * 9 + col + 1] else 0)
    return f"{bits:016x}"


def inspect_image(path: Path, *, thumbnail: int | None = None) -> ImageInfo:
    """Open, verify and fully decode ``path``; never raises for a broken image."""
    try:
        with Image.open(path) as probe:
            probe.verify()
        with Image.open(path) as image:
            image.load()
            orientation = image.getexif().get(EXIF_ORIENTATION)
            thumb = None
            if thumbnail is not None:
                thumb = (
                    image.convert("L")
                    .resize((thumbnail, thumbnail), Image.Resampling.BOX)
                    .tobytes()
                )
            return ImageInfo(
                ok=True,
                width=image.width,
                height=image.height,
                format=image.format,
                mode=image.mode,
                exif_orientation=int(orientation) if orientation else None,
                dhash=dhash64(image),
                thumbnail=thumb,
            )
    except (
        OSError,
        SyntaxError,
        ValueError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
    ) as exc:
        return ImageInfo(ok=False, error=f"{type(exc).__name__}: {exc}"[:200])
