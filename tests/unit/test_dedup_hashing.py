from __future__ import annotations

import math

import numpy as np
import pytest
from PIL import Image, ImageEnhance

from openinspect.dedup.hashing import (
    HASH_BITS,
    PHASH_LOW,
    PHASH_SIZE,
    hamming,
    hamming_block,
    hash_hex,
    hex_to_uint64,
    pairs_within,
    phash_int,
)
from tests.dedup_helpers import make_image


def reference_phash(image: Image.Image) -> int:
    """The textbook definition with an explicit (slow) 2-D DCT-II."""
    gray = image.convert("L").resize((PHASH_SIZE, PHASH_SIZE), Image.Resampling.LANCZOS)
    pixels = np.asarray(gray, dtype=np.float64)
    n = PHASH_SIZE
    dct = np.zeros((n, n))
    for u in range(n):
        for v in range(n):
            total = 0.0
            for x in range(n):
                for y in range(n):
                    total += (
                        pixels[x, y]
                        * math.cos(math.pi * (2 * x + 1) * u / (2 * n))
                        * math.cos(math.pi * (2 * y + 1) * v / (2 * n))
                    )
            dct[u, v] = total
    low = dct[:PHASH_LOW, :PHASH_LOW]
    median = float(np.median(low))
    value = 0
    for bit in (low > median).ravel():
        value = (value << 1) | int(bit)
    return value


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_phash_follows_the_textbook_definition(seed: int) -> None:
    image = make_image(seed, size=(64, 64))
    assert phash_int(image) == reference_phash(image)


def test_phash_is_stable_under_mild_changes_and_differs_between_images() -> None:
    image = make_image(5)
    brighter = ImageEnhance.Brightness(image).enhance(1.05)
    other = make_image(6)
    assert phash_int(image) == phash_int(image)
    assert hamming(phash_int(image), phash_int(brighter)) <= 6
    assert hamming(phash_int(image), phash_int(other)) >= 10


def test_hash_text_round_trip_and_validation() -> None:
    value = phash_int(make_image(7))
    text = hash_hex(value)
    assert len(text) == 16
    assert int(hex_to_uint64([text])[0]) == value
    with pytest.raises(ValueError, match="16 hexadecimal digits"):
        hex_to_uint64(["abc"])


def test_hamming_counts_differing_bits() -> None:
    assert hamming(0, 0) == 0
    assert hamming(0, 2**64 - 1) == HASH_BITS
    assert hamming(0b1010, 0b0110) == 2


def test_hamming_block_matches_python_popcount() -> None:
    rng = np.random.default_rng(0)
    a = rng.integers(0, 2**63, size=7, dtype=np.uint64)
    b = rng.integers(0, 2**63, size=5, dtype=np.uint64)
    block = hamming_block(a, b)
    assert block.shape == (7, 5)
    for i in range(7):
        for j in range(5):
            assert block[i, j] == (int(a[i]) ^ int(b[j])).bit_count()


def test_pairs_within_finds_exactly_the_close_pairs() -> None:
    rng = np.random.default_rng(1)
    hashes = rng.integers(0, 2**63, size=40, dtype=np.uint64)
    hashes[10] = hashes[3] ^ np.uint64(0b111)  # 3 bits apart
    hashes[20] = hashes[3]  # identical
    i, j, d = pairs_within(hashes, 4, chunk=7)  # a chunk size that does not divide 40
    found = {(int(a), int(b)): int(x) for a, b, x in zip(i, j, d, strict=True)}
    expected = {
        (a, b): (int(hashes[a]) ^ int(hashes[b])).bit_count()
        for a in range(40)
        for b in range(a + 1, 40)
        if (int(hashes[a]) ^ int(hashes[b])).bit_count() <= 4
    }
    assert found == expected
    assert found[(3, 20)] == 0
    assert found[(3, 10)] == 3


def test_pairs_within_with_nothing_close_is_empty() -> None:
    hashes = np.array([0, 2**64 - 1], dtype=np.uint64)
    i, j, d = pairs_within(hashes, 10)
    assert len(i) == len(j) == len(d) == 0
