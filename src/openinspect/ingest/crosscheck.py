"""Comparing two annotation sets of the same image, and small statistics used as grouping evidence."""

from __future__ import annotations

import random
import statistics
from collections.abc import Sequence
from dataclasses import dataclass

from openinspect.ingest.formats import Box


@dataclass(frozen=True)
class BoxMatch:
    """Result of pairing the boxes of two annotation sets one-to-one (same label, nearest first)."""

    deviations: tuple[float, ...]  # largest coordinate difference per matched pair, in pixels
    only_a: int
    only_b: int

    @property
    def max_deviation(self) -> float:
        return max(self.deviations, default=0.0)


def match_boxes(a: Sequence[Box], b: Sequence[Box]) -> BoxMatch:
    """Greedy one-to-one matching on the largest coordinate difference, within the same label."""
    pairs = sorted(
        (max(abs(p - q) for p, q in zip(x.xyxy, y.xyxy, strict=True)), i, j)
        for i, x in enumerate(a)
        for j, y in enumerate(b)
        if x.label == y.label
    )
    used_a: set[int] = set()
    used_b: set[int] = set()
    deviations: list[float] = []
    for deviation, i, j in pairs:
        if i not in used_a and j not in used_b:
            used_a.add(i)
            used_b.add(j)
            deviations.append(deviation)
    return BoxMatch(tuple(deviations), len(a) - len(used_a), len(b) - len(used_b))


def box_in_bounds(box: Box, width: int, height: int, tolerance: float = 0.5) -> bool:
    return (
        box.x1 > box.x0
        and box.y1 > box.y0
        and box.x0 >= -tolerance
        and box.y0 >= -tolerance
        and box.x1 <= width + tolerance
        and box.y1 <= height + tolerance
    )


def _normalised(vector: bytes) -> list[float]:
    mean = sum(vector) / len(vector)
    centred = [v - mean for v in vector]
    norm = sum(v * v for v in centred) ** 0.5 or 1.0
    return [v / norm for v in centred]


@dataclass(frozen=True)
class NeighbourTest:
    n: int
    hits: int  # images whose most similar other image has the same group
    chance: float  # hit rate expected if groups were unrelated to appearance

    @property
    def rate(self) -> float:
        return self.hits / self.n if self.n else 0.0


def nearest_neighbour_test(thumbnails: Sequence[bytes], groups: Sequence[str]) -> NeighbourTest:
    """Does the most similar other image (by thumbnail correlation) share the image's group?"""
    vectors = [_normalised(t) for t in thumbnails]
    n = len(vectors)
    hits = 0
    for i, vi in enumerate(vectors):
        best, best_j = -2.0, -1
        for j, vj in enumerate(vectors):
            if i != j:
                score = sum(p * q for p, q in zip(vi, vj, strict=True))
                if score > best:
                    best, best_j = score, j
        hits += groups[best_j] == groups[i]
    sizes: dict[str, int] = {}
    for g in groups:
        sizes[g] = sizes.get(g, 0) + 1
    chance = sum(s * (s - 1) for s in sizes.values()) / (n * (n - 1)) if n > 1 else 0.0
    return NeighbourTest(n, hits, chance)


@dataclass(frozen=True)
class LocalityTest:
    pairs: int
    adjacent_median: float
    random_median: float
    adjacent_close: float  # share of adjacent pairs at most ``close_bits`` apart
    random_close: float


def locality_test(
    hashes: Sequence[int], *, close_bits: int = 8, samples: int = 3000, seed: int = 0
) -> LocalityTest:
    """Are neighbours in a sequence more alike (dHash distance) than random pairs of the sequence?"""
    adjacent = [(hashes[i] ^ hashes[i + 1]).bit_count() for i in range(len(hashes) - 1)]
    rng = random.Random(seed)  # noqa: S311 - deterministic sampling, not cryptography
    sampled = [
        (hashes[a] ^ hashes[b]).bit_count()
        for a, b in (rng.sample(range(len(hashes)), 2) for _ in range(samples))
    ]
    return LocalityTest(
        pairs=len(adjacent),
        adjacent_median=statistics.median(adjacent),
        random_median=statistics.median(sampled),
        adjacent_close=sum(d <= close_bits for d in adjacent) / len(adjacent),
        random_close=sum(d <= close_bits for d in sampled) / len(sampled),
    )
