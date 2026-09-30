"""Leakage graph: images are nodes, similar pairs are edges, groups are connected components (M3E).

Connected components chain: a long path of moderately similar images ends up in one component even
when its two ends look nothing alike. Every component therefore carries the statistics of *all*
its member pairs next to the edge statistics, and ``percolation`` shows how the largest component
grows as the threshold drops.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from openinspect.dedup.similarity import pairs_above

Edges = tuple[NDArray[np.int64], NDArray[np.int64], NDArray[np.float32]]


class GraphError(Exception):
    """A graph cannot be built as asked (for example too many edges for memory)."""


class UnionFind:
    """Disjoint sets over ``0..n-1``; the representative of a set is its smallest member."""

    def __init__(self, n: int) -> None:
        self.parent = list(range(n))
        self.size = [1] * n
        self.n_components = n

    def find(self, item: int) -> int:
        parent = self.parent
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(self, a: int, b: int) -> int | None:
        """Join the sets of ``a`` and ``b``; returns the size of the new set, ``None`` if already joined."""
        root_a, root_b = self.find(a), self.find(b)
        if root_a == root_b:
            return None
        if root_b < root_a:  # keep the smallest member as the representative
            root_a, root_b = root_b, root_a
        self.parent[root_b] = root_a
        self.size[root_a] += self.size[root_b]
        self.n_components -= 1
        return self.size[root_a]

    def labels(self) -> NDArray[np.int64]:
        return np.array([self.find(i) for i in range(len(self.parent))], dtype=np.int64)


def collect_edges(
    vectors: NDArray[np.float32], threshold: float, *, max_edges: int = 30_000_000
) -> Edges:
    """All pairs with cosine >= ``threshold``; refuses to hold more than ``max_edges`` in memory."""
    rows: list[NDArray[np.int64]] = []
    cols: list[NDArray[np.int64]] = []
    sims: list[NDArray[np.float32]] = []
    total = 0
    for i, j, s in pairs_above(vectors, threshold):
        total += len(i)
        if total > max_edges:
            raise GraphError(
                f"more than {max_edges:,} pairs reach {threshold}: the threshold is too low to hold the edges"
            )
        rows.append(i)
        cols.append(j)
        sims.append(s)
    if not rows:
        return np.empty(0, np.int64), np.empty(0, np.int64), np.empty(0, np.float32)
    return np.concatenate(rows), np.concatenate(cols), np.concatenate(sims)


def components(
    n: int, edges: Iterable[tuple[NDArray[np.int64], NDArray[np.int64]]]
) -> NDArray[np.int64]:
    """Component label (the smallest member index) of every node."""
    forest = UnionFind(n)
    for i, j in edges:
        for a, b in zip(i.tolist(), j.tolist(), strict=True):
            forest.union(a, b)
    return forest.labels()


@dataclass(frozen=True)
class Group:
    label: int  # smallest member index
    members: NDArray[np.int64]  # sorted


def multi_member_groups(labels: NDArray[np.int64]) -> list[Group]:
    """Components with at least two members, ordered by their smallest member."""
    order = np.argsort(labels, kind="stable")
    sorted_labels = labels[order]
    boundaries = np.flatnonzero(np.diff(sorted_labels)) + 1
    groups: list[Group] = []
    for chunk in np.split(order, boundaries):
        if len(chunk) >= 2:
            members = np.sort(chunk)
            groups.append(Group(int(members[0]), members))
    groups.sort(key=lambda group: group.label)
    return groups


@dataclass(frozen=True)
class PairStats:
    minimum: float
    maximum: float
    mean: float
    n_pairs: int


def member_pair_stats(
    vectors: NDArray[np.float32], members: NDArray[np.int64], *, chunk: int = 2048
) -> PairStats:
    """Minimum, maximum and mean cosine over all pairs of ``members`` (not only over the edges)."""
    sub = vectors[members]
    m = len(sub)
    low, high, total, count = np.inf, -np.inf, 0.0, 0
    for start in range(0, m, chunk):
        stop = min(start + chunk, m)
        block = (sub[start:stop] @ sub[start:].T).astype(np.float64)
        rows = np.arange(stop - start)[:, None]
        cols = np.arange(m - start)[None, :]
        mask = cols > rows
        values = block[mask]
        if values.size == 0:  # the last rows can hold no pair of their own
            continue
        low = min(low, float(values.min()))
        high = max(high, float(values.max()))
        total += float(values.sum())
        count += int(values.size)
    return PairStats(low, high, total / count, count)


@dataclass(frozen=True)
class Percolation:
    """State of the graph after admitting every edge down to ``threshold``."""

    threshold: float
    edges: int
    groups: int  # components with at least two members
    images_in_groups: int
    largest: int


def percolation(n: int, edges: Edges, thresholds: Sequence[float]) -> list[Percolation]:
    """Group count and largest component as the threshold drops (one sweep over sorted edges)."""
    i, j, sims = edges
    order = np.argsort(-sims, kind="stable")
    ordered_i, ordered_j, ordered_s = i[order].tolist(), j[order].tolist(), sims[order].tolist()
    forest = UnionFind(n)
    cursor = 0
    n_groups = images_in = largest = 0
    out: list[Percolation] = []
    for threshold in sorted(thresholds, reverse=True):
        while cursor < len(ordered_s) and ordered_s[cursor] >= threshold:
            a, b = ordered_i[cursor], ordered_j[cursor]
            size_a, size_b = forest.size[forest.find(a)], forest.size[forest.find(b)]
            merged = forest.union(a, b)
            if merged is not None:
                if size_a == 1 and size_b == 1:
                    n_groups += 1
                    images_in += 2
                elif size_a == 1 or size_b == 1:
                    images_in += 1
                else:
                    n_groups -= 1
                largest = max(largest, merged)
            cursor += 1
        out.append(Percolation(threshold, cursor, n_groups, images_in, largest))
    return out


def edge_stats_by_label(
    labels: NDArray[np.int64], edges: Edges
) -> dict[int, tuple[int, float, float]]:
    """(number of edges, weakest edge, mean edge) of every component that has edges."""
    i, _, sims = edges
    label_of_edge = labels[i]
    result: dict[int, tuple[int, float, float]] = {}
    order = np.argsort(label_of_edge, kind="stable")
    sorted_labels = label_of_edge[order]
    sorted_sims = sims[order].astype(np.float64)
    starts = np.concatenate(([0], np.flatnonzero(np.diff(sorted_labels)) + 1))
    stops = np.concatenate((starts[1:], [len(sorted_labels)]))
    for start, stop in zip(starts.tolist(), stops.tolist(), strict=True):
        part = sorted_sims[start:stop]
        result[int(sorted_labels[start])] = (int(part.size), float(part.min()), float(part.mean()))
    return result
