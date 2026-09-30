from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from numpy.typing import NDArray

from openinspect.dedup.graph import Edges, collect_edges, components
from openinspect.dedup.inventory import ImageItem
from openinspect.dedup.leakage import (
    build_group_rows,
    key_overlap,
    max_similarity_to_train,
    permutation_baseline,
    reconstruct_split,
    source_leakage,
    split_codes,
)


def item(
    index: int,
    split: str | None,
    *,
    source: str = "s",
    group: str | None = None,
    subgroup: str | None = None,
    annotations: int = 1,
) -> ImageItem:
    return ImageItem(
        source=source,
        item_id=f"img/{index:03d}.png",
        path=Path(f"/nonexistent/{index}.png"),
        sha256=f"{index:064x}",
        split=split,
        group_id=group,
        subgroup_id=subgroup,
        n_annotations=annotations,
        dhash=0,
        width=10,
        height=10,
    )


# 12 images: train 0-5, val 6-8, test 9-11.
SPLITS = ["train"] * 6 + ["val"] * 3 + ["test"] * 3
GROUPS = [[0, 1, 6], [2, 9], [7, 10], [3, 4]]  # train|val, train|test, val|test, train only


def scenario() -> tuple[list[ImageItem], NDArray[np.int64], Edges]:
    items = [item(i, SPLITS[i], annotations=i + 1) for i in range(12)]
    pairs = [(0, 1), (0, 6), (2, 9), (7, 10), (3, 4)]
    i = np.array([a for a, _ in pairs], dtype=np.int64)
    j = np.array([b for _, b in pairs], dtype=np.int64)
    sims = np.array([0.9, 0.85, 0.95, 0.8, 0.99], dtype=np.float32)
    labels = components(12, [(i, j)])
    return items, labels, (i, j, sims)


def test_split_codes() -> None:
    items = [item(0, "train"), item(1, "val"), item(2, "test"), item(3, None)]
    assert split_codes(items).tolist() == [0, 1, 2, -1]


def test_leakage_numbers_of_a_known_scenario() -> None:
    items, labels, edges = scenario()
    result = source_leakage("s", items, labels, edges, level="family", threshold=0.8)
    assert result.groups == 4
    assert result.singletons == 3  # images 5, 8 and 11
    assert result.images_in_groups == 9
    assert result.largest_group == 3
    assert (result.crossing.train_val, result.crossing.train_test, result.crossing.val_test) == (
        1,
        1,
        1,
    )
    assert result.groups_crossing_any == 3
    assert result.affected_images == 3 + 2 + 2
    assert result.affected_annotations == (1 + 2 + 7) + (3 + 10) + (
        8 + 11
    )  # n_annotations = index + 1
    assert result.n_annotations == sum(range(1, 13))
    assert result.has_splits is True
    by_split = {n.split: n for n in result.eval_neighbour}
    assert by_split["val"].images == 3
    assert by_split["val"].with_train_neighbour == 1  # image 6 is next to train image 0
    assert (
        by_split["test"].with_train_neighbour == 1
    )  # image 9 is next to train image 2; 10 only to val
    assert by_split["val"].fraction == pytest.approx(1 / 3)


def test_a_source_without_splits_has_no_crossing_numbers() -> None:
    items = [item(i, None) for i in range(4)]
    labels = np.array([0, 0, 2, 3], dtype=np.int64)
    edges = (
        np.array([0], dtype=np.int64),
        np.array([1], dtype=np.int64),
        np.array([0.9], dtype=np.float32),
    )
    result = source_leakage("s", items, labels, edges, level="near", threshold=0.9)
    assert result.has_splits is False
    assert result.groups_crossing_any == 0
    assert result.eval_neighbour == []
    assert result.groups == 1


def test_similarity_to_train_is_a_threshold_free_distribution() -> None:
    vectors = np.array([[1, 0], [0, 1], [0.6, 0.8], [1, 0]], dtype=np.float32)
    codes = np.array([0, 0, 1, 2], dtype=np.int8)  # train, train, val, test
    out = max_similarity_to_train(vectors, codes)
    assert out["val"] is not None
    assert out["val"].median == pytest.approx(0.8, abs=1e-6)  # best train match of (0.6, 0.8)
    assert out["test"] is not None
    assert out["test"].median == pytest.approx(1.0, abs=1e-6)


def test_the_permutation_baseline_separates_random_from_group_aware_splits() -> None:
    rng = np.random.default_rng(0)
    n_pairs = 300
    labels = np.repeat(np.arange(n_pairs) * 2, 2).astype(np.int64)  # components {2k, 2k+1}
    # a split that ignores the groups: every image is assigned independently
    random_codes = (rng.random(2 * n_pairs) < 0.2).astype(np.int8)
    random_result = permutation_baseline(labels, random_codes, n_permutations=300, seed=1)
    assert random_result is not None
    assert random_result.p_lower > 0.01
    assert random_result.p_upper > 0.01
    assert abs(random_result.observed - random_result.null_mean) < 4 * random_result.null_sd
    # a split that keeps every pair together: fewer crossings than chance, by construction
    aware = np.repeat((rng.random(n_pairs) < 0.2).astype(np.int8), 2)
    aware_result = permutation_baseline(labels, aware, n_permutations=300, seed=1)
    assert aware_result is not None
    assert aware_result.observed == 0
    assert aware_result.p_lower <= 1 / 300 + 1e-9
    assert aware_result.null_mean > 50


def test_the_permutation_baseline_needs_a_complete_split() -> None:
    labels = np.array([0, 0, 2], dtype=np.int64)
    assert permutation_baseline(labels, np.array([0, 1, -1], dtype=np.int8)) is None
    assert permutation_baseline(np.array([], dtype=np.int64), np.array([], dtype=np.int8)) is None
    singletons = permutation_baseline(
        np.arange(4, dtype=np.int64), np.array([0, 1, 0, 1], dtype=np.int8)
    )
    assert singletons is not None
    assert (singletons.observed, singletons.null_mean) == (0, 0.0)


def test_a_reconstructed_split_cuts_no_group_and_keeps_the_sizes() -> None:
    rng = np.random.default_rng(3)
    n = 120
    raw = rng.standard_normal((n, 16))  # few random pairs are similar: small groups, no chaining
    vectors = (raw / np.linalg.norm(raw, axis=1, keepdims=True)).astype(np.float32)
    items = [item(i, "train" if i % 5 else "val") for i in range(n)]
    i, j, s = collect_edges(vectors, 0.6)
    labels = components(n, [(i, j)])
    result = reconstruct_split(items, labels, vectors, threshold=0.6, seed=0)
    assert result is not None
    assert result.groups_crossing == 0
    assert result.ratios == {"train": 96, "val": 24}
    assert sum(result.counts.values()) == n
    assert result.max_ratio_error < 0.1
    assert result.official_val_to_train is not None
    assert result.val_to_train is not None
    # with groups kept whole, no validation image has a train neighbour at or above the threshold
    assert result.val_to_train.maximum < 0.6 + 1e-6
    assert len(s) > 0


def test_a_reconstruction_needs_a_complete_official_split() -> None:
    items = [item(0, "train"), item(1, None)]
    vectors = np.eye(2, dtype=np.float32)
    assert (
        reconstruct_split(items, np.array([0, 1], dtype=np.int64), vectors, threshold=0.5) is None
    )


def keyed_scenario() -> tuple[list[ImageItem], NDArray[np.int64], Edges]:
    items = [
        item(0, "train", group="b1", subgroup="b1_t"),
        item(1, "train", group="b1", subgroup="b1_t"),
        item(2, "val", group="b1", subgroup="b1_b"),  # same batch, other side, other split
        item(3, "train", group="b2", subgroup="b2_t"),
        item(4, "val", group="b3", subgroup="b3_t"),  # similar to image 3 but another batch
        item(5, "test", group="b4", subgroup="b4_t"),
    ]
    pairs = [(0, 1), (1, 2), (3, 4)]
    i = np.array([a for a, _ in pairs], dtype=np.int64)
    j = np.array([b for _, b in pairs], dtype=np.int64)
    edges = (i, j, np.array([0.9, 0.85, 0.88], dtype=np.float32))
    return items, components(6, [(i, j)]), edges


def test_similarity_groups_are_compared_with_the_source_grouping_key() -> None:
    items, labels, edges = keyed_scenario()
    result = key_overlap(
        "s",
        items,
        labels,
        edges,
        level="family",
        threshold=0.8,
        key_group_name="batch",
        key_subgroup_name="batch and side",
    )
    assert result is not None
    mix = result.edge_mix
    assert (mix.edges, mix.same_subgroup, mix.same_group_other_subgroup, mix.other_group) == (
        3,
        1,
        1,
        1,
    )
    assert mix.cross_split_edges == 2  # (1, 2) and (3, 4)
    assert mix.cross_split_same_group_other_subgroup == 1
    assert mix.cross_split_other_group == 1
    assert result.images_with_key == 6
    # images 0-2 (batch b1) cross splits under the key; images 0-2 and 3-4 do under similarity
    assert result.key_cross_split_images == 3
    assert result.similarity_cross_split_images == 5
    assert (result.both, result.only_key, result.only_similarity, result.neither) == (3, 0, 2, 1)
    assert (
        result.cross_split_groups_with_several_keys == 1
    )  # the group {3, 4} spans batches b2 and b3
    assert result.vs_group.n_images == 6
    assert result.vs_group.pair_precision == pytest.approx(3 / 4)  # pairs 01 02 12 vs 34


def test_a_source_without_a_key_has_no_overlap_analysis() -> None:
    items = [item(i, "train") for i in range(3)]
    labels = np.array([0, 0, 2], dtype=np.int64)
    edges = (
        np.array([0], dtype=np.int64),
        np.array([1], dtype=np.int64),
        np.array([0.9], dtype=np.float32),
    )
    assert (
        key_overlap(
            "s",
            items,
            labels,
            edges,
            level="family",
            threshold=0.8,
            key_group_name="-",
            key_subgroup_name="-",
        )
        is None
    )


def test_group_rows_carry_members_sources_splits_and_statistics() -> None:
    rng = np.random.default_rng(4)
    raw = rng.standard_normal((6, 5))
    vectors = (raw / np.linalg.norm(raw, axis=1, keepdims=True)).astype(np.float32)
    items = [
        item(0, "train", source="a", group="g1", annotations=2),
        item(1, "val", source="a", group="g1", annotations=3),
        item(2, "train", source="b", group="h1"),
        item(3, "train", source="a"),
        item(4, "test", source="a"),
        item(5, "test", source="a"),
    ]
    i = np.array([0, 1, 4], dtype=np.int64)
    j = np.array([1, 2, 5], dtype=np.int64)
    sims = np.array([0.9, 0.8, 0.95], dtype=np.float32)
    labels = components(6, [(i, j)])
    rows = build_group_rows(
        items, vectors, labels, (i, j, sims), level="family", threshold=0.8, prefix="VG-F"
    )
    assert [r.group_id for r in rows] == ["VG-F-00001", "VG-F-00002"]
    first, second = rows
    assert len(first.members) == 3
    assert first.sources == ["a", "b"]
    assert first.cross_source is True
    assert first.cross_split is True
    assert first.crosses == ["a:train|val"]
    assert first.splits == ["a:train", "a:val", "b:train"]
    assert first.n_annotations == 2 + 3 + 1
    assert first.n_edges == 2
    assert first.edge_min_similarity == pytest.approx(0.8, abs=1e-6)
    assert first.all_pairs_min_similarity <= first.all_pairs_mean_similarity
    assert first.all_pairs_mean_similarity <= first.all_pairs_max_similarity
    assert first.size == len(first.members)
    assert first.chaining_gap == pytest.approx(
        first.edge_min_similarity - first.all_pairs_min_similarity
    )
    assert first.n_keys == 2
    assert second.cross_split is False  # both test images
    assert second.sources == ["a"]
    assert second.crosses == []
    assert second.all_pairs_max_similarity == pytest.approx(
        float(vectors[4] @ vectors[5]), abs=1e-5
    )


def test_a_chain_is_one_component_and_its_gap_shows_it() -> None:
    # A ~ B and B ~ C at the threshold, while A and C are far apart
    a = np.array([1.0, 0.0], dtype=np.float32)
    c = np.array([0.0, 1.0], dtype=np.float32)
    b = (a + c) / np.linalg.norm(a + c)
    vectors = np.stack([a, b.astype(np.float32), c])
    items = [item(0, "train"), item(1, "train"), item(2, "val")]
    i = np.array([0, 1], dtype=np.int64)
    j = np.array([1, 2], dtype=np.int64)
    sims = np.array([vectors[0] @ vectors[1], vectors[1] @ vectors[2]], dtype=np.float32)
    labels = components(3, [(i, j)])
    (row,) = build_group_rows(
        items, vectors, labels, (i, j, sims), level="family", threshold=0.7, prefix="VSG-family"
    )
    assert row.size == 3
    assert row.edge_min_similarity == pytest.approx(np.sqrt(0.5), abs=1e-6)
    assert row.all_pairs_min_similarity == pytest.approx(0.0, abs=1e-6)  # A and C
    assert row.chaining_gap == pytest.approx(np.sqrt(0.5), abs=1e-6)
    assert row.cross_split is True  # the chain reaches the validation image
