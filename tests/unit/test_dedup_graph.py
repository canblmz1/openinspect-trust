from __future__ import annotations

import random

import numpy as np
import pytest
from numpy.typing import NDArray

from openinspect.dedup.graph import (
    GraphError,
    UnionFind,
    collect_edges,
    components,
    edge_stats_by_label,
    member_pair_stats,
    multi_member_groups,
    percolation,
)
from openinspect.dedup.similarity import pairs_above


def unit_vectors(n: int, dim: int, seed: int) -> NDArray[np.float32]:
    raw = np.random.default_rng(seed).standard_normal((n, dim))
    return (raw / np.linalg.norm(raw, axis=1, keepdims=True)).astype(np.float32)


def bfs_labels(n: int, pairs: list[tuple[int, int]]) -> list[int]:
    adjacency: dict[int, list[int]] = {i: [] for i in range(n)}
    for a, b in pairs:
        adjacency[a].append(b)
        adjacency[b].append(a)
    label = [-1] * n
    for start in range(n):
        if label[start] >= 0:
            continue
        stack, seen = [start], {start}
        while stack:
            node = stack.pop()
            for nxt in adjacency[node]:
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        for node in seen:
            label[node] = min(seen)
    return label


def test_union_find_keeps_the_smallest_member_as_the_label() -> None:
    forest = UnionFind(6)
    assert forest.union(3, 4) == 2
    assert forest.union(4, 1) == 3
    assert forest.union(1, 3) is None  # already joined
    assert forest.labels().tolist() == [0, 1, 2, 1, 1, 5]
    assert forest.n_components == 4


def test_components_equal_a_breadth_first_search() -> None:
    rng = random.Random(0)
    n = 80
    pairs = [(rng.randrange(n), rng.randrange(n)) for _ in range(70)]
    pairs = [(a, b) for a, b in pairs if a != b]
    i = np.array([a for a, _ in pairs], dtype=np.int64)
    j = np.array([b for _, b in pairs], dtype=np.int64)
    got = components(n, [(i[:30], j[:30]), (i[30:], j[30:])])  # edges may arrive in chunks
    assert got.tolist() == bfs_labels(n, pairs)


def test_multi_member_groups_skip_singletons_and_are_ordered() -> None:
    labels = np.array([0, 1, 0, 3, 1, 5, 0], dtype=np.int64)
    groups = multi_member_groups(labels)
    assert [(g.label, g.members.tolist()) for g in groups] == [(0, [0, 2, 6]), (1, [1, 4])]
    assert multi_member_groups(np.arange(4, dtype=np.int64)) == []


def test_collect_edges_equals_the_streamed_pairs_and_honours_the_limit() -> None:
    vectors = unit_vectors(40, 3, 1)
    i, j, s = collect_edges(vectors, 0.5)
    streamed = sorted(
        (a, b)
        for ii, jj, _ in pairs_above(vectors, 0.5)
        for a, b in zip(ii.tolist(), jj.tolist(), strict=True)
    )
    assert sorted(zip(i.tolist(), j.tolist(), strict=True)) == streamed
    assert len(s) == len(i)
    with pytest.raises(GraphError, match="too low"):
        collect_edges(vectors, -1.0, max_edges=10)
    none = collect_edges(vectors, 2.0)
    assert len(none[0]) == 0


def test_percolation_equals_recomputing_the_groups_at_each_threshold() -> None:
    vectors = unit_vectors(60, 4, 2)
    edges = collect_edges(vectors, 0.3)
    thresholds = [0.9, 0.7, 0.5, 0.3]
    swept = percolation(60, edges, thresholds)
    assert [p.threshold for p in swept] == sorted(thresholds, reverse=True)
    for point in swept:
        keep = edges[2] >= point.threshold
        labels = components(60, [(edges[0][keep], edges[1][keep])])
        groups = multi_member_groups(labels)
        assert point.edges == int(keep.sum())
        assert point.groups == len(groups)
        assert point.images_in_groups == sum(len(g.members) for g in groups)
        assert point.largest == max((len(g.members) for g in groups), default=0)


def test_member_pair_stats_cover_all_pairs_not_only_edges() -> None:
    vectors = unit_vectors(12, 5, 3)
    members = np.array([1, 4, 5, 9, 11], dtype=np.int64)
    stats = member_pair_stats(vectors, members, chunk=2)
    wide = vectors.astype(np.float64)
    values = [float(wide[a] @ wide[b]) for x, a in enumerate(members) for b in members[x + 1 :]]
    assert stats.n_pairs == len(values) == 10
    assert stats.minimum == pytest.approx(min(values), abs=1e-6)
    assert stats.maximum == pytest.approx(max(values), abs=1e-6)
    assert stats.mean == pytest.approx(sum(values) / len(values), abs=1e-6)


def test_edge_statistics_per_component() -> None:
    labels = np.array([0, 0, 0, 3, 3, 5], dtype=np.int64)
    edges = (
        np.array([0, 0, 3], dtype=np.int64),
        np.array([1, 2, 4], dtype=np.int64),
        np.array([0.9, 0.7, 0.8], dtype=np.float32),
    )
    info = edge_stats_by_label(labels, edges)
    assert set(info) == {0, 3}
    n_edges, weakest, mean = info[0]
    assert n_edges == 2
    assert weakest == pytest.approx(0.7, abs=1e-6)
    assert mean == pytest.approx(0.8, abs=1e-6)
    assert info[3][0] == 1


def test_edge_statistics_of_a_graph_without_edges_are_empty() -> None:
    empty = (np.empty(0, np.int64), np.empty(0, np.int64), np.empty(0, np.float32))
    assert edge_stats_by_label(np.arange(3, dtype=np.int64), empty) == {}
