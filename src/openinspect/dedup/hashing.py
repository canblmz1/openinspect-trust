"""Perceptual hashes and Hamming distances (M3A).

Pure NumPy and Pillow, so the hash audit needs no extra dependency. ``phash`` follows the usual
definition (32x32 grayscale, 2-D DCT, the 8x8 low-frequency block compared with its median); the
64-bit difference hash (``dhash``) is the one already stored by ingest.
"""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np
from numpy.typing import NDArray
from PIL import Image

PHASH_SIZE = 32
PHASH_LOW = 8
PHASH_VERSION = "phash-v1"
HASH_BITS = 64


def _dct_matrix(n: int) -> NDArray[np.float64]:
    k = np.arange(n, dtype=np.float64)[:, None]
    i = np.arange(n, dtype=np.float64)[None, :]
    return np.cos(np.pi * (2.0 * i + 1.0) * k / (2.0 * n))


_DCT = _dct_matrix(PHASH_SIZE)


def phash_int(image: Image.Image) -> int:
    """64-bit perceptual hash of ``image`` as an unsigned integer (first bit is the most significant)."""
    gray = image.convert("L").resize((PHASH_SIZE, PHASH_SIZE), Image.Resampling.LANCZOS)
    pixels = np.asarray(gray, dtype=np.float64)
    dct = _DCT @ pixels @ _DCT.T
    low = dct[:PHASH_LOW, :PHASH_LOW]
    bits = (low > np.median(low)).ravel()
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return value


def hash_hex(value: int) -> str:
    return f"{value:016x}"


def hex_to_uint64(values: list[str]) -> NDArray[np.uint64]:
    """Parse 16-digit hexadecimal hashes; raises ``ValueError`` on a malformed one."""
    out = np.empty(len(values), dtype=np.uint64)
    for index, text in enumerate(values):
        if len(text) != 16:
            raise ValueError(f"a 64-bit hash has 16 hexadecimal digits, got {text!r}")
        out[index] = np.uint64(int(text, 16))
    return out


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def hamming_block(a: NDArray[np.uint64], b: NDArray[np.uint64]) -> NDArray[np.uint8]:
    """All Hamming distances between the hashes of ``a`` (rows) and ``b`` (columns)."""
    return np.bitwise_count(a[:, None] ^ b[None, :])


def pairs_within(
    hashes: NDArray[np.uint64], max_distance: int, *, chunk: int = 512
) -> tuple[NDArray[np.int64], NDArray[np.int64], NDArray[np.uint8]]:
    """Every pair ``i < j`` whose hashes differ in at most ``max_distance`` bits (exact, streamed)."""
    rows: list[NDArray[np.int64]] = []
    cols: list[NDArray[np.int64]] = []
    dists: list[NDArray[np.uint8]] = []
    for start, block in _upper_blocks(hashes, chunk):
        rel_i, rel_j = np.nonzero(block <= max_distance)
        rows.append(rel_i.astype(np.int64) + start)
        cols.append(rel_j.astype(np.int64) + start)
        dists.append(block[rel_i, rel_j])
    if not rows:
        empty = np.empty(0, dtype=np.int64)
        return empty, empty.copy(), np.empty(0, dtype=np.uint8)
    return np.concatenate(rows), np.concatenate(cols), np.concatenate(dists)


def _upper_blocks(
    hashes: NDArray[np.uint64], chunk: int
) -> Iterator[tuple[int, NDArray[np.uint8]]]:
    """Distance blocks; entry (r, c) is the pair (start + r, start + c), and only ``c > r`` is valid.

    Invalid entries (the diagonal and below) are set to 255, which is larger than any distance.
    """
    n = len(hashes)
    for start in range(0, n, chunk):
        stop = min(start + chunk, n)
        block = hamming_block(hashes[start:stop], hashes[start:])
        rows = np.arange(stop - start)[:, None]
        cols = np.arange(n - start)[None, :]
        yield start, np.where(cols > rows, block, np.uint8(255)).astype(np.uint8)
