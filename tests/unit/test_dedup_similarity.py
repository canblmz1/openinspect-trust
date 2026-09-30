from __future__ import annotations

import numpy as np
import pytest
from numpy.typing import NDArray

from openinspect.dedup.similarity import (
    check_normalised,
    count_pairs_above,
    iter_upper_blocks,
    pair_similarity,
    pairs_above,
    topk_cosine,
)


def unit_vectors(n: int, dim: int = 8, seed: int = 0) -> NDArray[np.float32]:
    rng = np.random.default_rng(seed)
    raw = rng.standard_normal((n, dim))
    return (raw / np.linalg.norm(raw, axis=1, keepdims=True)).astype(np.float32)


def brute_matrix(vectors: NDArray[np.float32]) -> NDArray[np.float64]:
    wide = vectors.astype(np.float64)
    return wide @ wide.T


def test_topk_equals_brute_force_for_several_chunk_sizes() -> None:
    vectors = unit_vectors(57)
    full = brute_matrix(vectors)
    np.fill_diagonal(full, -np.inf)
    for chunk in (1, 10, 57, 1000):
        indices, sims = topk_cosine(vectors, 5, chunk=chunk)
        for i in range(57):
            order = sorted(range(57), key=lambda j: (-full[i, j], j))[:5]
            assert indices[i].tolist() == order
            assert np.allclose(sims[i], full[i, order], atol=1e-6)


def test_topk_never_returns_the_vector_itself_and_clamps_k() -> None:
    vectors = unit_vectors(4)
    indices, _ = topk_cosine(vectors, 10)
    assert indices.shape == (4, 3)
    assert all(i not in row for i, row in enumerate(indices.tolist()))
    empty_idx, empty_sims = topk_cosine(unit_vectors(1), 3)
    assert empty_idx.shape == (1, 0)
    assert empty_sims.shape == (1, 0)


def test_topk_breaks_ties_by_the_smaller_index() -> None:
    base = unit_vectors(1, seed=3)
    others = unit_vectors(3, seed=4)
    vectors = np.concatenate([others[:1], base, base, base, others[1:]])  # rows 1, 2, 3 identical
    indices, sims = topk_cosine(vectors, 3)
    assert indices[1].tolist()[:2] == [2, 3]
    assert indices[2].tolist()[:2] == [1, 3]
    assert indices[3].tolist()[:2] == [1, 2]
    assert np.allclose(sims[1][:2], 1.0, atol=1e-6)


def test_the_upper_blocks_cover_each_pair_once() -> None:
    vectors = unit_vectors(23)
    seen = set()
    for start, block in iter_upper_blocks(vectors, chunk=5):
        rows, cols = np.nonzero(np.isfinite(block))
        for r, c in zip(rows.tolist(), cols.tolist(), strict=True):
            pair = (start + r, start + c)
            assert pair[0] < pair[1]
            assert pair not in seen
            seen.add(pair)
    assert len(seen) == 23 * 22 // 2


def test_pairs_above_and_counts_match_brute_force() -> None:
    vectors = unit_vectors(40, dim=3)  # few dimensions, so plenty of similar pairs
    full = brute_matrix(vectors)
    expected = {
        (a, b): full[a, b] for a in range(40) for b in range(a + 1, 40) if full[a, b] >= 0.8
    }
    found = {}
    for i, j, s in pairs_above(vectors, 0.8, chunk=6):
        for a, b, value in zip(i.tolist(), j.tolist(), s.tolist(), strict=True):
            found[(a, b)] = value
    assert found.keys() == expected.keys()
    assert all(abs(found[k] - expected[k]) < 1e-5 for k in found)
    counts = count_pairs_above(vectors, [0.8, 0.0, 2.0], chunk=6)
    assert counts[0] == len(expected)
    assert counts[1] == sum(1 for a in range(40) for b in range(a + 1, 40) if full[a, b] >= 0)
    assert counts[2] == 0


def test_normalisation_check() -> None:
    vectors = unit_vectors(5)
    check_normalised(vectors)
    with pytest.raises(ValueError, match="L2-normalised"):
        check_normalised(vectors * 2)


def test_pair_similarity_is_the_dot_product() -> None:
    vectors = unit_vectors(3)
    assert abs(pair_similarity(vectors, 0, 1) - float(vectors[0] @ vectors[1])) < 1e-6
    assert abs(pair_similarity(vectors, 2, 2) - 1.0) < 1e-6
