"""Split leakage measured on similarity groups (M3E, M3F, M3G).

A similarity group is a connected component of the graph of image pairs whose cosine is at or
above a threshold. It is a *visual similarity group*, evidence of a potential leakage group, not a
proof that two images show the same physical board.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from pydantic import Field

from openinspect.dedup.graph import (
    Edges,
    Group,
    edge_stats_by_label,
    member_pair_stats,
    multi_member_groups,
)
from openinspect.dedup.inventory import ImageItem
from openinspect.dedup.metrics import PartitionAgreement, Quantiles, partition_agreement, quantiles
from openinspect.dedup.split_helper import group_aware_split, groups_crossing
from openinspect.provenance.schema import StrictModel

SPLITS = ("train", "val", "test")
SPLIT_CODE = {name: code for code, name in enumerate(SPLITS)}
Level = str  # "near" | "family" | "review"


def split_codes(items: Sequence[ImageItem]) -> NDArray[np.int8]:
    """0 train, 1 val, 2 test, -1 for an image without a split."""
    return np.array([SPLIT_CODE.get(item.split or "", -1) for item in items], dtype=np.int8)


class SplitCrossing(StrictModel):
    train_val: int = 0
    train_test: int = 0
    val_test: int = 0


class NeighbourLeak(StrictModel):
    """Images of an evaluation split that have a direct neighbour at or above the threshold in train."""

    split: str
    images: int
    with_train_neighbour: int
    fraction: float | None


class SourceLeakage(StrictModel):
    source: str
    level: str
    threshold: float
    n_images: int
    n_annotations: int
    groups: int = Field(description="similarity groups with two or more images")
    singletons: int
    images_in_groups: int
    largest_group: int
    has_splits: bool
    crossing: SplitCrossing
    groups_crossing_any: int
    affected_images: int
    affected_annotations: int
    eval_neighbour: list[NeighbourLeak]


def source_leakage(
    source: str,
    items: Sequence[ImageItem],
    labels: NDArray[np.int64],
    edges: Edges,
    *,
    level: Level,
    threshold: float,
) -> SourceLeakage:
    """Leakage numbers of one source for the groups of ``labels`` (local indices, within-source edges)."""
    codes = split_codes(items)
    groups = multi_member_groups(labels)
    has_splits = bool((codes >= 0).any())
    crossing = {"train_val": 0, "train_test": 0, "val_test": 0}
    crossing_any = affected_images = affected_annotations = 0
    annotations = np.array([item.n_annotations for item in items], dtype=np.int64)
    for group in groups:
        known = codes[group.members]
        bits = 0
        for code in known.tolist():
            if code >= 0:
                bits |= 1 << code
        if bits.bit_count() < 2:
            continue
        crossing_any += 1
        affected_images += len(group.members)
        affected_annotations += int(annotations[group.members].sum())
        crossing["train_val"] += int(bits & 0b011 == 0b011)
        crossing["train_test"] += int(bits & 0b101 == 0b101)
        crossing["val_test"] += int(bits & 0b110 == 0b110)
    neighbour: list[NeighbourLeak] = []
    if has_splits:
        mask = np.zeros(len(items), dtype=np.int8)
        i, j, _ = edges
        for a, b in zip(i.tolist(), j.tolist(), strict=True):
            ca, cb = int(codes[a]), int(codes[b])
            if ca >= 0 and cb >= 0 and ca != cb:
                mask[a] |= 1 << cb
                mask[b] |= 1 << ca
        for split in ("val", "test"):
            selected = codes == SPLIT_CODE[split]
            if selected.any():
                with_train = int(np.count_nonzero(selected & ((mask & 1) != 0)))
                neighbour.append(
                    NeighbourLeak(
                        split=split,
                        images=int(selected.sum()),
                        with_train_neighbour=with_train,
                        fraction=with_train / int(selected.sum()),
                    )
                )
    sizes = [len(g.members) for g in groups]
    return SourceLeakage(
        source=source,
        level=level,
        threshold=threshold,
        n_images=len(items),
        n_annotations=int(annotations.sum()),
        groups=len(groups),
        singletons=len(items) - sum(sizes),
        images_in_groups=sum(sizes),
        largest_group=max(sizes, default=1),
        has_splits=has_splits,
        crossing=SplitCrossing(**crossing),
        groups_crossing_any=crossing_any,
        affected_images=affected_images,
        affected_annotations=affected_annotations,
        eval_neighbour=neighbour,
    )


def max_similarity_to_train(
    vectors: NDArray[np.float32], codes: NDArray[np.int8]
) -> dict[str, Quantiles | None]:
    """Distribution, per evaluation split, of each image's highest cosine to any training image."""
    train = np.flatnonzero(codes == SPLIT_CODE["train"])
    out: dict[str, Quantiles | None] = {}
    for split in ("val", "test"):
        rows = np.flatnonzero(codes == SPLIT_CODE[split])
        if len(rows) == 0 or len(train) == 0:
            continue
        best = np.empty(len(rows), dtype=np.float32)
        for start in range(0, len(rows), 1024):
            block = vectors[rows[start : start + 1024]] @ vectors[train].T
            best[start : start + 1024] = block.max(axis=1)
        out[split] = quantiles(best)
    return out


class PermutationBaseline(StrictModel):
    """Cross-split groups of the real split against the same groups under random splits of equal sizes."""

    n_permutations: int
    observed: int
    null_mean: float
    null_sd: float
    p_lower: float = Field(
        description="share of random splits with at most as many crossing groups"
    )
    p_upper: float = Field(description="share of random splits with at least as many")


def permutation_baseline(
    labels: NDArray[np.int64],
    codes: NDArray[np.int8],
    *,
    n_permutations: int = 1000,
    seed: int = 0,
) -> PermutationBaseline | None:
    """``None`` when some image has no split (the baseline is only defined for a complete split)."""
    if len(codes) == 0 or (codes < 0).any():
        return None
    groups = multi_member_groups(labels)
    if not groups:
        return PermutationBaseline(
            n_permutations=n_permutations,
            observed=0,
            null_mean=0.0,
            null_sd=0.0,
            p_lower=1.0,
            p_upper=1.0,
        )
    members = np.concatenate([g.members for g in groups])
    starts = np.concatenate(([0], np.cumsum([len(g.members) for g in groups])[:-1]))

    def crossing_count(assignment: NDArray[np.int8]) -> int:
        values = assignment[members]
        return int(
            np.count_nonzero(
                np.minimum.reduceat(values, starts) != np.maximum.reduceat(values, starts)
            )
        )

    observed = crossing_count(codes)
    rng = np.random.default_rng(seed)
    null = np.array(
        [crossing_count(rng.permutation(codes)) for _ in range(n_permutations)], dtype=np.float64
    )
    return PermutationBaseline(
        n_permutations=n_permutations,
        observed=observed,
        null_mean=float(null.mean()),
        null_sd=float(null.std(ddof=1)) if n_permutations > 1 else 0.0,
        p_lower=float((null <= observed).mean()),
        p_upper=float((null >= observed).mean()),
    )


class Reconstructed(StrictModel):
    """What a split that keeps every similarity group whole looks like, with the same split sizes."""

    threshold: float
    ratios: dict[str, int]  # images per split in the official split
    counts: dict[str, int]  # images per split after reconstruction
    max_ratio_error: float  # largest |reconstructed share - official share|
    groups_crossing: int
    val_to_train: Quantiles | None
    test_to_train: Quantiles | None
    official_val_to_train: Quantiles | None
    official_test_to_train: Quantiles | None


def reconstruct_split(
    items: Sequence[ImageItem],
    labels: NDArray[np.int64],
    vectors: NDArray[np.float32],
    *,
    threshold: float,
    seed: int = 0,
) -> Reconstructed | None:
    """Reassign whole similarity groups to splits, keeping the official split sizes."""
    official = split_codes(items)
    if (official < 0).any() or len(items) == 0:
        return None
    counts = Counter(SPLITS[int(c)] for c in official)
    ratios = {name: counts[name] for name in SPLITS if counts[name] > 0}
    assignment = group_aware_split(
        [int(x) for x in labels], {k: float(v) for k, v in ratios.items()}, seed=seed
    )
    new_codes = np.array([SPLIT_CODE[name] for name in assignment], dtype=np.int8)
    n = len(items)
    new_counts = Counter(assignment)
    error = max(abs(new_counts[name] / n - ratios[name] / n) for name in ratios)
    official_dist = max_similarity_to_train(vectors, official)
    new_dist = max_similarity_to_train(vectors, new_codes)
    return Reconstructed(
        threshold=threshold,
        ratios=ratios,
        counts={name: new_counts[name] for name in ratios},
        max_ratio_error=error,
        groups_crossing=groups_crossing([int(x) for x in labels], assignment),
        val_to_train=new_dist.get("val"),
        test_to_train=new_dist.get("test"),
        official_val_to_train=official_dist.get("val"),
        official_test_to_train=official_dist.get("test"),
    )


class EdgeMix(StrictModel):
    """How the similar pairs of a source relate to its grouping key."""

    edges: int
    same_subgroup: int
    same_group_other_subgroup: int
    other_group: int
    cross_split_edges: int
    cross_split_same_subgroup: int
    cross_split_same_group_other_subgroup: int
    cross_split_other_group: int


class KeyOverlap(StrictModel):
    source: str
    level: str
    threshold: float
    key_group_name: str
    key_subgroup_name: str
    images_with_key: int
    vs_group: PartitionAgreement
    vs_subgroup: PartitionAgreement
    edge_mix: EdgeMix
    key_cross_split_images: int | None
    similarity_cross_split_images: int | None
    both: int | None
    only_key: int | None
    only_similarity: int | None
    neither: int | None
    cross_split_groups_with_several_keys: int | None


def key_overlap(
    source: str,
    items: Sequence[ImageItem],
    labels: NDArray[np.int64],
    edges: Edges,
    *,
    level: Level,
    threshold: float,
    key_group_name: str,
    key_subgroup_name: str,
) -> KeyOverlap | None:
    """How similarity groups line up with the source's own grouping key; ``None`` without a key."""
    if not any(item.group for item in items):
        return None
    from openinspect.dedup.calibrate import codes as make_codes

    group_codes = make_codes([item.group for item in items])
    subgroup_codes = make_codes([item.subgroup for item in items])
    predicted = [int(x) for x in labels]
    vs_group = partition_agreement(predicted, [int(x) for x in group_codes])
    vs_subgroup = partition_agreement(predicted, [int(x) for x in subgroup_codes])
    split_arr = split_codes(items)
    i, j, _ = edges
    mix = Counter[str]()
    for a, b in zip(i.tolist(), j.tolist(), strict=True):
        if group_codes[a] < 0 or group_codes[b] < 0:
            continue
        if subgroup_codes[a] >= 0 and subgroup_codes[a] == subgroup_codes[b]:
            kind = "same_subgroup"
        elif group_codes[a] == group_codes[b]:
            kind = "same_group_other_subgroup"
        else:
            kind = "other_group"
        mix[kind] += 1
        if split_arr[a] >= 0 and split_arr[b] >= 0 and split_arr[a] != split_arr[b]:
            mix["cross_" + kind] += 1
    edge_mix = EdgeMix(
        edges=len(i),
        same_subgroup=mix["same_subgroup"],
        same_group_other_subgroup=mix["same_group_other_subgroup"],
        other_group=mix["other_group"],
        cross_split_edges=mix["cross_same_subgroup"]
        + mix["cross_same_group_other_subgroup"]
        + mix["cross_other_group"],
        cross_split_same_subgroup=mix["cross_same_subgroup"],
        cross_split_same_group_other_subgroup=mix["cross_same_group_other_subgroup"],
        cross_split_other_group=mix["cross_other_group"],
    )
    has_splits = bool((split_arr >= 0).all()) and len(items) > 0
    key_cross = sim_cross = both = only_key = only_sim = neither = several = None
    if has_splits:
        splits_of_key: dict[int, set[int]] = {}
        for code, split in zip(group_codes.tolist(), split_arr.tolist(), strict=True):
            if code >= 0:
                splits_of_key.setdefault(code, set()).add(split)
        key_flag = np.array(
            [
                group_codes[n] >= 0 and len(splits_of_key[int(group_codes[n])]) > 1
                for n in range(len(items))
            ]
        )
        sim_flag = np.zeros(len(items), dtype=bool)
        several = 0
        for group in multi_member_groups(labels):
            if len(set(split_arr[group.members].tolist())) > 1:
                sim_flag[group.members] = True
                if (
                    len(
                        {int(group_codes[m]) for m in group.members.tolist() if group_codes[m] >= 0}
                    )
                    > 1
                ):
                    several += 1
        key_cross = int(key_flag.sum())
        sim_cross = int(sim_flag.sum())
        both = int((key_flag & sim_flag).sum())
        only_key = int((key_flag & ~sim_flag).sum())
        only_sim = int((~key_flag & sim_flag).sum())
        neither = int((~key_flag & ~sim_flag).sum())
    return KeyOverlap(
        source=source,
        level=level,
        threshold=threshold,
        key_group_name=key_group_name,
        key_subgroup_name=key_subgroup_name,
        images_with_key=int((group_codes >= 0).sum()),
        vs_group=vs_group,
        vs_subgroup=vs_subgroup,
        edge_mix=edge_mix,
        key_cross_split_images=key_cross,
        similarity_cross_split_images=sim_cross,
        both=both,
        only_key=only_key,
        only_similarity=only_sim,
        neither=neither,
        cross_split_groups_with_several_keys=several,
    )


@dataclass(frozen=True)
class GroupRow:
    """One similarity group, ready for the leakage-groups table."""

    group_id: str
    level: str
    threshold: float
    members: list[str]
    sources: list[str]
    splits: list[str]
    n_annotations: int
    max_similarity: float
    min_similarity: float
    mean_similarity: float
    n_edges: int
    min_edge_similarity: float
    cross_split: bool
    crosses: list[str]
    cross_source: bool
    n_keys: int


def build_group_rows(
    items: Sequence[ImageItem],
    vectors: NDArray[np.float32],
    labels: NDArray[np.int64],
    edges: Edges,
    *,
    level: Level,
    threshold: float,
    prefix: str,
) -> list[GroupRow]:
    """Rows for the groups of two or more images of a graph over ``items`` (any number of sources)."""
    edge_info = edge_stats_by_label(labels, edges)
    rows: list[GroupRow] = []
    for number, group in enumerate(multi_member_groups(labels), start=1):
        rows.append(
            _row(items, vectors, group, edge_info, level, threshold, f"{prefix}-{number:05d}")
        )
    return rows


def _row(
    items: Sequence[ImageItem],
    vectors: NDArray[np.float32],
    group: Group,
    edge_info: dict[int, tuple[int, float, float]],
    level: Level,
    threshold: float,
    group_id: str,
) -> GroupRow:
    member_items = [items[m] for m in group.members.tolist()]
    stats = member_pair_stats(vectors, group.members)
    n_edges, weakest_edge, _ = edge_info.get(group.label, (0, float("nan"), float("nan")))
    per_source: dict[str, set[str]] = {}
    for item in member_items:
        if item.split:
            per_source.setdefault(item.source, set()).add(item.split)
    crosses = [
        f"{source}:{'|'.join(sorted(splits, key=SPLIT_CODE.__getitem__))}"
        for source, splits in sorted(per_source.items())
        if len(splits) > 1
    ]
    keys = {(item.source, item.group) for item in member_items if item.group}
    sources = sorted({item.source for item in member_items})
    return GroupRow(
        group_id=group_id,
        level=level,
        threshold=threshold,
        members=[f"{item.source}:{item.item_id}" for item in member_items],
        sources=sources,
        splits=sorted(
            f"{source}:{split}" for source, splits in per_source.items() for split in splits
        ),
        n_annotations=sum(item.n_annotations for item in member_items),
        max_similarity=stats.maximum,
        min_similarity=stats.minimum,
        mean_similarity=stats.mean,
        n_edges=n_edges,
        min_edge_similarity=weakest_edge,
        cross_split=bool(crosses),
        crosses=crosses,
        cross_source=len(sources) > 1,
        n_keys=len(keys),
    )
