"""Reading, decoding and deterministic preprocessing of images for the audit (M3B).

Preprocessing version ``v1``: the whole image (no crop) is resized to 224x224 with Pillow's
bicubic filter, scaled to [0, 1] and normalised with the ImageNet mean and standard deviation.
No crop, because a printed-circuit crop has no meaningful centre; no aspect-ratio padding, because
a consistent squash is enough for similarity. The version string is part of every cache key, so a
change to this function needs a new version.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PIL import Image, UnidentifiedImageError

PREPROCESSING_VERSION = "v1"
INPUT_SIZE = 224
IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

# Same decompression-bomb limit as ingest: PCB-Defect scans reach about 31 megapixels.
Image.MAX_IMAGE_PIXELS = 200_000_000


class DecodeError(Exception):
    """An image could not be read or decoded."""


class ReadError(DecodeError):
    """The file could not be read, or is not the file that ingest recorded."""


class IntegrityError(ReadError):
    """The bytes on disk are not the bytes that ingest recorded."""


def read_verified(path: Path, expected_sha256: str) -> bytes:
    """Read ``path`` and check it against the SHA-256 that ingest recorded."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ReadError(f"cannot read {path.name}: {exc}") from exc
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected_sha256:
        raise IntegrityError(
            f"{path.name}: SHA-256 {actual[:12]}... differs from the recorded {expected_sha256[:12]}..."
        )
    return data


def decode_rgb(data: bytes) -> Image.Image:
    """Decode completely and convert to RGB; raises :class:`DecodeError` for a broken file."""
    try:
        with Image.open(io.BytesIO(data)) as opened:
            opened.load()
            return opened.convert("RGB")
    except (
        OSError,
        SyntaxError,
        ValueError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
    ) as exc:
        raise DecodeError(f"{type(exc).__name__}: {exc}"[:200]) from exc


def preprocess(image: Image.Image, size: int = INPUT_SIZE) -> NDArray[np.float32]:
    """Model input for ``image``: float32, shape (3, size, size), ImageNet-normalised."""
    resized = image.convert("RGB").resize((size, size), Image.Resampling.BICUBIC)
    scaled = np.asarray(resized, dtype=np.float32) / np.float32(255.0)
    normalised = (scaled - IMAGENET_MEAN) / IMAGENET_STD
    return np.ascontiguousarray(normalised.transpose(2, 0, 1), dtype=np.float32)
