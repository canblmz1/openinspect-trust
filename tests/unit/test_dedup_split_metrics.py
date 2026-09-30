from __future__ import annotations

import random
from collections import Counter

import numpy as np
import pytest

from openinspect.dedup.metrics import partition_agreement, quantiles
from openinspect.dedup.split_helper import (
    SplitError,
    group_aware_split,
    groups_crossing,
    leave_one_source_out,
)

# ------------------------------------------------------------------------ group-aware split


def random_groups(seed: int, n_groups: int = 60) -> list[int]:
    rng = random.Random(seed)
    group_of: list[int] = []
    for group in range(n_groups):
        group_of.extend([group] * rng.randint(1, 7))
    rng.shuffle(group_of)
    return group_of


def test_no_group_is_ever_cut_by_a_split_boundary() -> None:
    group_of = random_groups(0)
    split = group_aware_split(group_of, {"train": 8, "val": 2}, seed=1)
    assert groups_crossing(group_of, split) == 0
    by_group: dict[int, set[str]] = {}
    for group, name in zip(group_of, split, strict=True):
        by_group.setdefault(group, set()).add(name)
    assert all(len(names) == 1 for names in by_group.values())


def test_the_ratios_are_followed_as_closely_as_the_group_sizes_allow() -> None:
    group_of = random_groups(1, n_groups=200)
    split = group_aware_split(group_of, {"train": 8, "val": 2}, seed=0)
    counts = Counter(split)
    share = counts["val"] / len(group_of)
    assert abs(share - 0.2) < 0.02
    three = group_aware_split(group_of, {"train": 6, "val": 2, "test": 2}, seed=0)
    shares = {k: v / len(three) for k, v in Counter(three).items()}
    assert abs(shares["train"] - 0.6) < 0.03
    assert abs(shares["test"] - 0.2) < 0.03


def test_the_split_is_a_pure_function_of_groups_ratios_and_seed() -> None:
    group_of = random_groups(2)
    a = group_aware_split(group_of, {"train": 7, "val": 3}, seed=5)
    assert a == group_aware_split(group_of, {"train": 7, "val": 3}, seed=5)
    assert a != group_aware_split(group_of, {"train": 7, "val": 3}, seed=6)


def test_groups_that_span_several_sources_stay_together() -> None:
    sources = ["a", "a", "b", "b", "a", "b", "c", "c"]
    group_of = [0, 1, 0, 1, 2, 2, 3, 4]  # groups 0, 1 and 2 each contain two sources
    split = group_aware_split(group_of, {"train": 1, "val": 1}, seed=0)
    for group in set(group_of):
        members = [split[i] for i, g in enumerate(group_of) if g == group]
        assert len(set(members)) == 1, f"group {group} of sources {sources} was cut"
    assert groups_crossing(group_of, split) == 0


def test_invalid_ratios_are_refused() -> None:
    with pytest.raises(SplitError, match="positive"):
        group_aware_split([0, 1], {"train": 1, "val": 0})
    with pytest.raises(SplitError, match="positive"):
        group_aware_split([0, 1], {})


def test_groups_crossing_counts_groups_not_images_and_ignores_unknown_splits() -> None:
    group_of = [0, 0, 0, 1, 1, 2, 2]
    split: list[str | None] = ["train", "val", "train", "train", "train", None, "val"]
    assert groups_crossing(group_of, split) == 1  # only group 0; group 2 has one known split


def test_leave_one_source_out_never_splits_a_source() -> None:
    sources = ["a", "b", "a", "c", "b"]
    assert leave_one_source_out(sources, "b") == ["train", "test", "train", "train", "test"]
    with pytest.raises(SplitError, match="not one of the sources"):
        leave_one_source_out(sources, "z")


# --------------------------------------------------------------------- partition agreement


def test_identical_partitions_agree_completely() -> None:
    labels = [0, 0, 1, 1, 2, 2, 2]
    result = partition_agreement(labels, labels)
    assert result.pair_precision == 1.0
    assert result.pair_recall == 1.0
    assert result.adjusted_rand == pytest.approx(1.0)
    assert result.homogeneity == pytest.approx(1.0)
    assert result.completeness == pytest.approx(1.0)
    assert result.multi_member_purity == 1.0


def test_a_worked_example() -> None:
    result = partition_agreement([0, 0, 1, 1], [0, 0, 0, 1])
    assert result.n_images == 4
    assert result.pair_precision == pytest.approx(1 / 2)
    assert result.pair_recall == pytest.approx(1 / 3)
    assert result.adjusted_rand == pytest.approx(0.0, abs=1e-12)
    assert result.homogeneity == pytest.approx(0.3837, abs=1e-3)
    assert result.completeness == pytest.approx(0.3113, abs=1e-3)
    assert result.v_measure == pytest.approx(0.3437, abs=1e-3)
    assert result.multi_member_purity == pytest.approx(3 / 4)


def test_images_without_a_label_are_left_out_and_tiny_inputs_are_undefined() -> None:
    result = partition_agreement([0, 0, -1, 1], [0, 0, 5, -1])
    assert result.n_images == 2
    assert result.pair_precision == 1.0
    undefined = partition_agreement([0], [0])
    assert undefined.adjusted_rand is None
    assert undefined.pair_precision is None


def test_singleton_clusters_have_no_precision() -> None:
    result = partition_agreement([0, 1, 2, 3], [0, 0, 1, 1])
    assert result.pair_precision is None  # no pair shares a cluster
    assert result.pair_recall == 0.0
    assert result.multi_member_purity is None


# --------------------------------------------------------------------------------- quantiles


def test_quantiles_of_a_known_sequence() -> None:
    q = quantiles(np.arange(101, dtype=np.float32))
    assert q is not None
    assert (q.n, q.minimum, q.maximum) == (101, 0.0, 100.0)
    assert q.median == pytest.approx(50.0)
    assert q.p05 == pytest.approx(5.0)
    assert q.p95 == pytest.approx(95.0)
    assert q.mean == pytest.approx(50.0)
    assert quantiles(np.array([], dtype=np.float32)) is None


def test_group_aware_split_keeps_groups_whole_but_not_sources() -> None:
    # six items of source "a" in three groups, six of source "b" in three groups
    sources = ["a"] * 6 + ["b"] * 6
    group_of = [0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5]
    split = group_aware_split(group_of, {"train": 2.0, "test": 1.0}, seed=0)
    assert groups_crossing(group_of, split) == 0  # group integrity holds
    per_source = {s: {sp for src, sp in zip(sources, split, strict=True) if src == s} for s in "ab"}
    assert per_source["a"] == {"train", "test"} or per_source["b"] == {"train", "test"}
    # source integrity is the job of the source-held-out assignment
    held_out = leave_one_source_out(sources, "b")
    assert {sp for src, sp in zip(sources, held_out, strict=True) if src == "b"} == {"test"}
    assert {sp for src, sp in zip(sources, held_out, strict=True) if src == "a"} == {"train"}
    source_as_group = [0 if s == "a" else 1 for s in sources]
    assert groups_crossing(source_as_group, held_out) == 0
