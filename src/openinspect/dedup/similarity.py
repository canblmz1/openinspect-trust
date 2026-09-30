"""Exact cosine similarity on L2-normalised embeddings (M3C).

At 15,278 vectors of 384 numbers an exact search costs seconds, so there is no approximate index:
the calibration and the leakage numbers carry no search error. Everything is streamed in row
blocks, so memory stays at ``chunk x n`` floats whatever the number of images.
"""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np
from numpy.typing import NDArray

DEFAULT_CHUNK = 1024


def check_normalised(vectors: NDArray[np.float32], tolerance: float = 1e-3) -> None:
    norms = np.linalg.norm(vectors.astype(np.float64), axis=1)
    if vectors.size and float(np.abs(norms - 1.0).max()) > tolerance:
        raise ValueError("vectors must be L2-normalised")


def topk_cosine(
    vectors: NDArray[np.float32], k: int, *, chunk: int = DEFAULT_CHUNK
) -> tuple[NDArray[np.int64], NDArray[np.float32]]:
    """The ``k`` most similar other vectors of every vector: indices and cosine, best first.

    Ties are broken by the smaller index, so the answer is a pure function of the input.
    """
    n = len(vectors)
    k = min(k, n - 1)
    if k < 1:
        return np.empty((n, 0), dtype=np.int64), np.empty((n, 0), dtype=np.float32)
    indices = np.empty((n, k), dtype=np.int64)
    sims = np.empty((n, k), dtype=np.float32)
    for start in range(0, n, chunk):
        stop = min(start + chunk, n)
        block = vectors[start:stop] @ vectors.T
        block[np.arange(stop - start), np.arange(start, stop)] = -np.inf  # never itself
        part = np.argpartition(-block, k - 1, axis=1)[:, :k]
        part_sims = np.take_along_axis(block, part, axis=1)
        order = np.lexsort((part, -part_sims), axis=1)
        indices[start:stop] = np.take_along_axis(part, order, axis=1)
        sims[start:stop] = np.take_along_axis(part_sims, order, axis=1)
    return indices, sims


def iter_upper_blocks(
    vectors: NDArray[np.float32], *, chunk: int = DEFAULT_CHUNK
) -> Iterator[tuple[int, NDArray[np.float32]]]:
    """Similarity blocks for all pairs (i, j) with j > i.

    Entry (r, c) of the block that starts at ``start`` is the similarity of vectors
    ``start + r`` and ``start + c``; only entries with ``c > r`` are pairs, the rest is ``-inf``.
    """
    n = len(vectors)
    for start in range(0, n, chunk):
        stop = min(start + chunk, n)
        block = vectors[start:stop] @ vectors[start:].T
        rows = np.arange(stop - start)[:, None]
        cols = np.arange(n - start)[None, :]
        block[cols <= rows] = -np.inf
        yield start, block


def pairs_above(
    vectors: NDArray[np.float32], threshold: float, *, chunk: int = DEFAULT_CHUNK
) -> Iterator[tuple[NDArray[np.int64], NDArray[np.int64], NDArray[np.float32]]]:
    """Every pair (i < j) with cosine similarity >= ``threshold``, in row blocks (exact)."""
    for start, block in iter_upper_blocks(vectors, chunk=chunk):
        rel_i, rel_j = np.nonzero(block >= threshold)
        if len(rel_i):
            yield (
                rel_i.astype(np.int64) + start,
                rel_j.astype(np.int64) + start,
                block[rel_i, rel_j],
            )


def count_pairs_above(
    vectors: NDArray[np.float32], thresholds: list[float], *, chunk: int = DEFAULT_CHUNK
) -> list[int]:
    """How many pairs reach each threshold (one pass over the data)."""
    counts = [0] * len(thresholds)
    for _, block in iter_upper_blocks(vectors, chunk=chunk):
        for index, threshold in enumerate(thresholds):
            counts[index] += int(np.count_nonzero(block >= threshold))
    return counts


def pair_similarity(vectors: NDArray[np.float32], i: int, j: int) -> float:
    return float(np.dot(vectors[i].astype(np.float64), vectors[j].astype(np.float64)))
