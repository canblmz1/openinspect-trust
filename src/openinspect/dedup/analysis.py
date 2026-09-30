"""The audit from cached features: calibration, thresholds, groups, leakage and review queue.

Every number of the M3 reports is computed here from three inputs: the L2-normalised embeddings,
the perceptual hashes and the synthetic pairs. Randomness appears only where the protocol puts it
(bootstrap, permutations, the reconstructed split, the review queue), always seeded. Nothing is
deleted, excluded or re-labelled (T15); the result is numbers, tables and a review queue.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace

import numpy as np
from numpy.typing import NDArray

from openinspect.dedup.audit_models import (
    Audit,
    BaselineCurve,
    CategoryCount,
    Cohesion,
    ComponentSummary,
    CrossSourceEdges,
    CrossSourceSummary,
    FailureInfo,
    GridPoint,
    HashAudit,
    HashScope,
    Interval,
    LevelResult,
    MetadataIntegrity,
    PercolationRow,
    PoolResult,
    Robustness,
    RobustnessRow,
    RunInfo,
    SourceCounts,
    Stability,
    SyntheticRecall,
    SyntheticSummary,
    Top1Stats,
    TransferRow,
    TransformSummary,
    UncertaintyCheck,
)
from openinspect.dedup.calibrate import (
    MIN_PAIRS,
    NBINS,
    Curve,
    Histograms,
    Pool,
    auc,
    average_precision,
    bootstrap_both_sides,
    bootstrap_positive_groups,
    codes,
    curve_from_histograms,
    hash_pool_histograms,
    metrics_at,
    pool_histograms,
    pool_pairs,
)
from openinspect.dedup.compute import FeatureSet
from openinspect.dedup.config import DedupConfig
from openinspect.dedup.embedder import EmbedderSpec
from openinspect.dedup.graph import (
    Edges,
    GraphError,
    UnionFind,
    collect_edges,
    edge_stats_by_label,
    member_pair_stats,
    multi_member_groups,
)
from openinspect.dedup.hashing import PHASH_VERSION, hamming_block, pairs_within
from openinspect.dedup.inventory import ImageItem, Unreadable
from openinspect.dedup.leakage import (
    SPLITS,
    GroupRow,
    KeyOverlap,
    PermutationBaseline,
    Reconstructed,
    SourceLeakage,
    build_group_rows,
    key_overlap,
    permutation_baseline,
    reconstruct_split,
    source_leakage,
    split_codes,
)
from openinspect.dedup.metrics import partition_agreement, quantiles
from openinspect.dedup.perf import StageTiming, timed
from openinspect.dedup.similarity import count_pairs_above, topk_cosine
from openinspect.dedup.synthetic import SyntheticPair
from openinspect.dedup.thresholds import (
    CATEGORIES,
    PHASH_AUTHORS,
    PoolCurve,
    Thresholds,
    classify_pairs,
    select_thresholds,
)
from openinspect.dedup.transforms import TRANSFORMS


class AnalysisError(Exception):
    """The audit cannot run on the given inputs."""


@dataclass(frozen=True)
class PoolSpec:
    """One calibration pool of a source (docs/M3_PROTOCOL.md section 5), in generic keys."""

    name: str
    positive: str  # "group_id" or "subgroup_id": two images sharing it form a positive pair
    negative: str  # "group_id" or "subgroup_id": two images differing in it form a negative pair
    used_in_rule: bool


LEVELS = ("near", "family")
DECISION = "review"  # M3 decides nothing: every pair waits for a human (SPEC 6.4)
CONTROL = "BELOW_REVIEW"  # review-queue stratum: nearest neighbours the rule does not flag
GENERIC_KEYS = ("group_id", "subgroup_id")


@dataclass(frozen=True)
class Settings:
    """Parameters of one audit. Source-specific meaning comes in through ``pools`` and ``key_names``."""

    seed: int = 0
    resamples: int = 1000
    permutations: int = 1000
    top_k: int = 10
    review_budget: int = 300
    stability_delta: float = 0.02
    chaining_share: float = 0.25
    max_edges: int = 30_000_000
    pools: Mapping[str, Sequence[PoolSpec]] = field(default_factory=dict)
    key_names: Mapping[str, tuple[str, str]] = field(default_factory=dict)  # source -> names
    acquisition: Mapping[str, str | None] = field(default_factory=dict)  # source -> acquisition id


def settings_from_config(config: DedupConfig, base: Settings | None = None) -> Settings:
    """``base`` with the pools, key names and acquisition ids that ``configs/dedup.yaml`` declares."""
    pools = {
        source: tuple(PoolSpec(p.name, p.positive, p.negative, p.used_in_rule) for p in entry.pools)
        for source, entry in config.sources.items()
        if entry.pools
    }
    names = {
        source: (entry.group_id or GENERIC_KEYS[0], entry.subgroup_id or GENERIC_KEYS[1])
        for source, entry in config.sources.items()
        if entry.group_id or entry.subgroup_id
    }
    acquisition = {source: entry.acquisition_id for source, entry in config.sources.items()}
    return replace(base or Settings(), pools=pools, key_names=names, acquisition=acquisition)


# ------------------------------------------------------------------------------- views


@dataclass(frozen=True)
class View:
    """The images of one source inside the feature set."""

    source: str
    index: NDArray[np.int64]  # positions in the feature set
    items: list[ImageItem]
    vectors: NDArray[np.float32]
    phash: NDArray[np.uint64]
    dhash: NDArray[np.uint64]
    splits: NDArray[np.int8]


def make_views(features: FeatureSet) -> list[View]:
    names = np.array([item.source for item in features.items])
    views: list[View] = []
    for source in sorted(set(names.tolist())):
        index = np.flatnonzero(names == source).astype(np.int64)
        items = [features.items[i] for i in index.tolist()]
        views.append(
            View(
                source=source,
                index=index,
                items=items,
                vectors=features.vectors[index],
                phash=features.phash[index],
                dhash=features.dhash[index],
                splits=split_codes(items),
            )
        )
    return views


def _round(value: float | None, digits: int = 6) -> float | None:
    return None if value is None or not math.isfinite(value) else round(value, digits)


def _r(value: float) -> float:
    return round(float(value), 6)


# ------------------------------------------------------------------------- calibration


@dataclass(frozen=True)
class PoolData:
    view: View
    spec: PoolSpec
    pool: Pool
    histograms: Histograms
    curve: Curve
    phash: tuple[NDArray[np.int64], NDArray[np.int64]]
    dhash: tuple[NDArray[np.int64], NDArray[np.int64]]


def calibration_pools(views: Sequence[View], settings: Settings) -> list[PoolData]:
    """Exact histograms of every labelled pair of every pool (all pairs of the source)."""
    out: list[PoolData] = []
    for view in views:
        for spec in settings.pools.get(view.source, ()):
            positive = codes([getattr(item, spec.positive) for item in view.items])
            negative = codes([getattr(item, spec.negative) for item in view.items])
            pool = Pool(f"{view.source}:{spec.name}", positive, negative)
            histograms = pool_histograms(view.vectors, pool)
            out.append(
                PoolData(
                    view=view,
                    spec=spec,
                    pool=pool,
                    histograms=histograms,
                    curve=curve_from_histograms(histograms.positive, histograms.negative),
                    phash=hash_pool_histograms(view.phash, pool),
                    dhash=hash_pool_histograms(view.dhash, pool),
                )
            )
    return out


def hash_baseline(
    name: str, positive: NDArray[np.int64], negative: NDArray[np.int64]
) -> BaselineCurve:
    """ROC AUC, average precision and best F1 of a Hamming distance used as a similarity score."""
    curve = curve_from_histograms(positive[::-1].copy(), negative[::-1].copy())  # index 64 - d
    f1 = np.where(curve.support >= MIN_PAIRS, curve.f1, -1.0)
    best_f1: float | None = None
    best_distance: int | None = None
    if curve.positives and float(f1.max()) > 0:
        best = int(len(f1) - 1 - np.argmax(f1[::-1]))  # the smallest distance among equals
        best_f1, best_distance = _r(f1[best]), len(f1) - 1 - best
    return BaselineCurve(
        name=name,
        auc=_round(auc(curve)),
        average_precision=_round(average_precision(curve)),
        best_f1=best_f1,
        best_distance=best_distance,
    )


def grid_point(curve: Curve, threshold: float) -> GridPoint:
    point = metrics_at(curve, threshold)
    return GridPoint(
        threshold=_r(threshold),
        precision=_round(point.precision),
        recall=_round(point.recall),
        f1=_round(point.f1),
        fpr=_round(point.fpr),
        pairs_above=point.pairs_above,
    )


def _interval(value: object) -> Interval | None:
    low, high = getattr(value, "low", None), getattr(value, "high", None)
    if low is None or high is None:
        return None
    return Interval(low=_r(low), high=_r(high))


def pool_result(data: PoolData, thresholds: Thresholds, settings: Settings) -> PoolResult:
    curve = data.curve
    boot = bootstrap_positive_groups(
        data.histograms, thresholds.family, resamples=settings.resamples, seed=settings.seed
    )
    sample = pool_pairs(data.view.vectors, data.pool)
    both = bootstrap_both_sides(
        sample, thresholds.family, resamples=settings.resamples, seed=settings.seed
    )
    uncertainty = [
        _uncertainty(name, getattr(boot, attr), getattr(both, attr))
        for name, attr in (
            ("ROC AUC", "auc"),
            ("average precision", "average_precision"),
            ("precision at family", "precision"),
            ("recall at family", "recall"),
        )
    ]
    levels = {"review": thresholds.review, "family": thresholds.family, "near": thresholds.near}
    at = {name: grid_point(curve, value) for name, value in levels.items()}
    grid = [grid_point(curve, k / 100) for k in range(0, 101)]
    roc: list[tuple[float, float]] = [(0.0, 0.0)]
    pr: list[tuple[float, float]] = []
    for k in range(100, -101, -1):
        point = metrics_at(curve, k / 100)
        if point.fpr is not None and point.recall is not None:
            roc.append((_r(point.fpr), _r(point.recall)))
        if point.precision is not None and point.recall is not None:
            pr.append((_r(point.recall), _r(point.precision)))
    per = NBINS // 200  # fine bins per 0.01 of cosine
    pos = data.histograms.positive.reshape(-1, per).sum(axis=1)
    neg = data.histograms.negative.reshape(-1, per).sum(axis=1)
    histogram = [
        (
            _r(-1.0 + b * 0.01),
            _r(pos[b] / max(curve.positives, 1)),
            _r(neg[b] / max(curve.negatives, 1)),
        )
        for b in range(len(pos))
        if pos[b] or neg[b]
    ]
    return PoolResult(
        source=data.view.source,
        pool=data.spec.name,
        used_in_rule=data.spec.used_in_rule,
        images=len(data.view.items),
        positives=curve.positives,
        negatives=curve.negatives,
        auc=_round(auc(curve)),
        auc_ci=_interval(boot.auc),
        average_precision=_round(average_precision(curve)),
        average_precision_ci=_interval(boot.average_precision),
        at_thresholds=at,
        precision_ci_at_family=_interval(boot.precision),
        recall_ci_at_family=_interval(boot.recall),
        grid=grid,
        roc=roc,
        pr=pr,
        histogram=histogram,
        baselines=[hash_baseline("phash", *data.phash), hash_baseline("dhash", *data.dhash)],
        positive_groups=len(data.histograms.group_positive),
        negative_units=sample.units,
        uncertainty=uncertainty,
    )


def _uncertainty(metric: str, primary: object, both_sides: object) -> UncertaintyCheck:
    first, second = _interval(primary), _interval(both_sides)
    ratio = None
    if first is not None and second is not None and first.high > first.low:
        ratio = _r((second.high - second.low) / (first.high - first.low))
    return UncertaintyCheck(metric=metric, primary=first, both_sides=second, width_ratio=ratio)


# --------------------------------------------------------------------------- synthetic


def _summary(
    transform: str, kind: str, near_duplicate: bool, pairs: Sequence[SyntheticPair], near: float
) -> TransformSummary | None:
    cos = np.array([p.cosine for p in pairs], dtype=np.float64)
    q = quantiles(cos)
    if q is None:
        return None
    photometric = [p.phash_distance for p in pairs if p.kind == "photometric"] or [
        p.phash_distance for p in pairs
    ]
    return TransformSummary(
        transform=transform,
        kind=kind,
        near_duplicate=near_duplicate,
        n=len(pairs),
        cosine=q,
        phash_p95=float(np.quantile(np.array(photometric, dtype=np.float64), 0.95)),
        share_near=_r(float((cos >= near).mean())),
    )


def synthetic_summary(
    synthetic: Sequence[SyntheticPair], thresholds: Thresholds, seed: int
) -> SyntheticSummary | None:
    if not synthetic:
        return None
    by_transform: list[TransformSummary] = []
    for transform in TRANSFORMS:
        own = [p for p in synthetic if p.transform == transform.name]
        row = _summary(
            transform.name, transform.kind, transform.near_duplicate, own, thresholds.near
        )
        if row is not None:
            by_transform.append(row)
    by_source: list[TransformSummary] = []
    for source in sorted({p.source for p in synthetic}):
        own = [p for p in synthetic if p.source == source and p.near_duplicate]
        row = _summary("near-duplicate set", source, True, own, thresholds.near)
        if row is not None:
            by_source.append(row)
    per_source = Counter(p.source for p in {(p.source, p.sha256): p for p in synthetic}.values())
    return SyntheticSummary(
        sample_per_source=max(per_source.values()),
        seed=seed,
        by_transform=by_transform,
        by_source=by_source,
    )


def synthetic_recall(
    synthetic: Sequence[SyntheticPair], thresholds: Thresholds
) -> list[SyntheticRecall]:
    """Achieved recall of each source's near-duplicate copies at the final near threshold."""
    rows: list[SyntheticRecall] = []
    for entry in thresholds.from_synthetic:
        cosines = np.array(
            [p.cosine for p in synthetic if p.source == entry.source and p.near_duplicate],
            dtype=np.float64,
        )
        if len(cosines) == 0:
            continue
        achieved = float((cosines >= thresholds.near).mean())
        rows.append(
            SyntheticRecall(
                source=entry.source,
                target_recall=thresholds.synthetic_recall,
                source_threshold=entry.near,
                final_near_threshold=thresholds.near,
                achieved_recall=_r(achieved),
                n_pairs=len(cosines),
                meets_target=achieved >= thresholds.synthetic_recall,
            )
        )
    return rows


def metadata_integrity(views: Sequence[View], settings: Settings) -> list[MetadataIntegrity]:
    """For each source with a split, how many values of its own keys occur in two or more splits."""
    rows: list[MetadataIntegrity] = []
    for view in views:
        names = settings.key_names.get(view.source, GENERIC_KEYS)
        for key, name in zip(GENERIC_KEYS, names, strict=True):
            splits_of: dict[str, set[str]] = {}
            images_of: Counter[str] = Counter()
            for item in view.items:
                value = getattr(item, key)
                if value is not None and item.split is not None:
                    splits_of.setdefault(value, set()).add(item.split)
                    images_of[value] += 1
            if not splits_of:
                continue
            crossing = [value for value, splits in splits_of.items() if len(splits) > 1]
            rows.append(
                MetadataIntegrity(
                    source=view.source,
                    key=key,
                    key_name=name,
                    values=len(splits_of),
                    crossing=len(crossing),
                    images_in_crossing=sum(images_of[value] for value in crossing),
                )
            )
    return rows


# ------------------------------------------------------------------------ neighbours


@dataclass(frozen=True)
class Neighbours:
    """Global top-k over all sources, and each image's most similar image inside its own source."""

    index: NDArray[np.int64]  # (n, k)
    cosine: NDArray[np.float32]
    within_top1: dict[str, NDArray[np.float32]]  # cosine, per source
    within_index: dict[str, NDArray[np.int64]]  # local index of that image, per source


def neighbours(features: FeatureSet, views: Sequence[View], k: int) -> Neighbours:
    index, cosine = topk_cosine(features.vectors, k)
    within: dict[str, NDArray[np.float32]] = {}
    within_index: dict[str, NDArray[np.int64]] = {}
    for view in views:
        idx, sims = topk_cosine(view.vectors, 1)
        within[view.source] = sims[:, 0] if sims.shape[1] else np.empty(0, dtype=np.float32)
        within_index[view.source] = idx[:, 0] if idx.shape[1] else np.empty(0, dtype=np.int64)
    return Neighbours(index, cosine, within, within_index)


def key_agreement(
    values: Sequence[str | None], top1: NDArray[np.int64]
) -> tuple[float | None, float | None]:
    """(share whose most similar image has the same key, the same for a random other image)."""
    keyed = [i for i, value in enumerate(values) if value is not None]
    if len(keyed) < 2 or len(top1) != len(values):
        return None, None
    same = [values[int(top1[i])] == values[i] for i in keyed]
    sizes = Counter(values[i] for i in keyed)
    n = len(keyed)
    chance = sum(c * (c - 1) for c in sizes.values()) / (n * (n - 1))
    return _r(sum(same) / len(same)), _r(chance)


def cdf(values: NDArray[np.float32]) -> list[tuple[float, float]]:
    """Share of ``values`` at or below each cosine from 0 to 1 in steps of 0.01."""
    if len(values) == 0:
        return []
    ordered = np.sort(values.astype(np.float64))
    return [
        (_r(k / 100), _r(np.searchsorted(ordered, k / 100, side="right") / len(ordered)))
        for k in range(0, 101)
    ]


def _share(values: NDArray[np.float32], threshold: float) -> float | None:
    return _r(float((values >= threshold).mean())) if len(values) else None


def top1_stats(
    features: FeatureSet, views: Sequence[View], near: Neighbours, thresholds: Thresholds
) -> list[Top1Stats]:
    source_of = np.array([item.source for item in features.items])
    rows: list[Top1Stats] = []
    for view in views:
        top1 = near.within_top1[view.source]
        other = np.zeros(len(view.index), dtype=bool)
        other_family = np.zeros(len(view.index), dtype=bool)
        if near.index.shape[1]:
            first = near.index[view.index, 0]
            other = source_of[first] != view.source
            other_family = other & (near.cosine[view.index, 0] >= thresholds.family)
        local = near.within_index[view.source]
        same_group, chance_group = key_agreement([item.group_id for item in view.items], local)
        same_sub, chance_sub = key_agreement([item.subgroup_id for item in view.items], local)
        rows.append(
            Top1Stats(
                source=view.source,
                images=len(view.items),
                within_source=quantiles(top1),
                share_review=_share(top1, thresholds.review),
                share_family=_share(top1, thresholds.family),
                share_near=_share(top1, thresholds.near),
                nearest_is_other_source=int(other.sum()),
                other_source_family=int(other_family.sum()),
                top1_same_group=same_group,
                top1_same_subgroup=same_sub,
                chance_same_group=chance_group,
                chance_same_subgroup=chance_sub,
                cdf=cdf(top1),
            )
        )
    return rows


def transfer_rows(
    views: Sequence[View], near: Neighbours, thresholds: Thresholds, settings: Settings
) -> list[TransferRow]:
    return [
        TransferRow(
            source=view.source,
            labelled=bool(settings.pools.get(view.source)),
            top1=quantiles(near.within_top1[view.source]),
            share_review=_share(near.within_top1[view.source], thresholds.review),
            share_family=_share(near.within_top1[view.source], thresholds.family),
            share_near=_share(near.within_top1[view.source], thresholds.near),
        )
        for view in views
    ]


# ---------------------------------------------------------------------------- graphs


def sweep_labels(
    n: int, edges: Edges, thresholds: Sequence[float]
) -> Iterator[tuple[float, int, NDArray[np.int64]]]:
    """(threshold, edges admitted, component labels) as the threshold drops; one pass over the edges."""
    i, j, sims = edges
    order = np.argsort(-sims, kind="stable")
    ordered_i, ordered_j = i[order].tolist(), j[order].tolist()
    ordered_s = sims[order]
    forest = UnionFind(n)
    cursor = 0
    for threshold in sorted(set(thresholds), reverse=True):
        stop = int(np.searchsorted(-ordered_s, -np.float32(threshold), side="right"))
        for position in range(cursor, stop):
            forest.union(ordered_i[position], ordered_j[position])
        cursor = max(cursor, stop)
        yield threshold, cursor, forest.labels()


def crossing(labels: NDArray[np.int64], splits: NDArray[np.int8]) -> tuple[int, int]:
    """(groups whose members sit in two or more known splits, images in those groups)."""
    if len(labels) == 0:
        return 0, 0
    order = np.argsort(labels, kind="stable")
    sorted_labels = labels[order]
    bits = np.where(splits[order] >= 0, np.left_shift(1, np.maximum(splits[order], 0)), 0)
    starts = np.concatenate(([0], np.flatnonzero(np.diff(sorted_labels)) + 1))
    union = np.bitwise_or.reduceat(bits.astype(np.int64), starts)
    sizes = np.diff(np.concatenate((starts, [len(labels)])))
    multi = np.array([int(u).bit_count() >= 2 for u in union.tolist()], dtype=bool)
    return int(multi.sum()), int(sizes[multi].sum())


def filter_edges(edges: Edges, threshold: float) -> Edges:
    i, j, sims = edges
    keep = sims >= np.float32(threshold)
    return i[keep], j[keep], sims[keep]


@dataclass
class SourceGraphs:
    view: View
    floor: float  # lowest threshold whose edges are held
    edges: Edges  # all pairs at or above ``floor`` (local indices)
    labels: dict[float, NDArray[np.int64]]  # component labels per checkpoint threshold
    admitted: dict[float, int]
    note: str | None


def sweep_grid(thresholds: Thresholds, delta: float) -> list[float]:
    """Checkpoints of the percolation sweep: 0.01 steps from the review threshold up, plus the rule's values."""
    grid = {_r(k / 100) for k in range(math.ceil(thresholds.review * 100), 100)}
    grid |= {
        thresholds.review,
        thresholds.family,
        thresholds.near,
        _r(thresholds.family - delta),
        _r(min(thresholds.family + delta, 1.0)),
    }
    return sorted(grid)


def source_graphs(
    view: View, grid: Sequence[float], max_edges: int, *, protected: float
) -> SourceGraphs:
    """Edges down to the lowest checkpoint that fits in memory, and the labels at every checkpoint."""
    floor = min(grid)
    note = None
    if count_pairs_above(view.vectors, [floor])[0] > max_edges:
        counts = count_pairs_above(view.vectors, list(grid))
        fitting = [t for t, c in zip(grid, counts, strict=True) if c <= max_edges]
        if not fitting or min(fitting) > protected:
            raise GraphError(
                f"{view.source}: more than {max_edges:,} pairs at the protected threshold {protected}"
            )
        floor = min(fitting)
        note = f"{view.source}: sweep starts at {floor} (more than {max_edges:,} pairs below)"
    edges = collect_edges(view.vectors, floor, max_edges=max_edges)
    kept = [t for t in grid if t >= floor]
    labels: dict[float, NDArray[np.int64]] = {}
    admitted: dict[float, int] = {}
    for threshold, count, lab in sweep_labels(len(view.items), edges, kept):
        labels[threshold] = lab
        admitted[threshold] = count
    return SourceGraphs(view, floor, edges, labels, admitted, note)


def cohesion(
    graphs: SourceGraphs, level: str, threshold: float, review: float, *, largest: int = 5
) -> Cohesion:
    """Member-pair statistics of every component, the chaining gap, and the largest components."""
    labels = graphs.labels[threshold]
    groups = multi_member_groups(labels)
    edge_info = edge_stats_by_label(labels, filter_edges(graphs.edges, threshold))
    split_names = [item.split or "none" for item in graphs.view.items]
    minima, means, gaps = [], [], []
    summaries: list[ComponentSummary] = []
    for group in groups:
        stats = member_pair_stats(graphs.view.vectors, group.members)
        _, edge_min, edge_mean = edge_info[group.label]
        minima.append(stats.minimum)
        means.append(stats.mean)
        gaps.append(edge_min - stats.minimum)
        summaries.append(
            ComponentSummary(
                size=len(group.members),
                share_of_source=_r(len(group.members) / len(graphs.view.items)),
                edge_min_similarity=_r(edge_min),
                edge_mean_similarity=_r(edge_mean),
                all_pairs_min_similarity=_r(stats.minimum),
                all_pairs_mean_similarity=_r(stats.mean),
                chaining_gap=_r(edge_min - stats.minimum),
                splits=sorted({split_names[m] for m in group.members.tolist()}),
            )
        )
    low = np.array(minima, dtype=np.float64)
    summaries.sort(key=lambda s: -s.size)  # stable: equal sizes keep the order of their members
    return Cohesion(
        source=graphs.view.source,
        level=level,
        groups=len(groups),
        min_pairwise=quantiles(low),
        mean_pairwise=quantiles(np.array(means, dtype=np.float64)),
        sizes=quantiles(np.array([len(g.members) for g in groups], dtype=np.float64)),
        share_below_review=_r(float((low < review).mean())) if len(low) else None,
        chaining_gap=quantiles(np.array(gaps, dtype=np.float64)),
        largest=summaries[:largest],
    )


def level_result(
    level: str,
    threshold: float,
    graphs: Sequence[SourceGraphs],
    thresholds: Thresholds,
    settings: Settings,
) -> LevelResult:
    leakage: list[SourceLeakage] = []
    overlaps: list[KeyOverlap] = []
    cohesions: list[Cohesion] = []
    chained: list[str] = []
    permutation: dict[str, PermutationBaseline | None] = {}
    reconstructed: dict[str, Reconstructed | None] = {}
    for g in graphs:
        view = g.view
        labels = g.labels[threshold]
        edges = filter_edges(g.edges, threshold)
        leak = source_leakage(
            view.source, view.items, labels, edges, level=level, threshold=threshold
        )
        leakage.append(leak)
        if leak.largest_group > settings.chaining_share * max(leak.n_images, 1):
            chained.append(view.source)
        group_name, subgroup_name = settings.key_names.get(view.source, GENERIC_KEYS)
        overlap = key_overlap(
            view.source,
            view.items,
            labels,
            edges,
            level=level,
            threshold=threshold,
            key_group_name=group_name,
            key_subgroup_name=subgroup_name,
        )
        if overlap is not None:
            overlaps.append(overlap)
        permutation[view.source] = permutation_baseline(
            labels, view.splits, n_permutations=settings.permutations, seed=settings.seed
        )
        reconstructed[view.source] = reconstruct_split(
            view.items, labels, view.vectors, threshold=threshold, seed=settings.seed
        )
        cohesions.append(cohesion(g, level, threshold, thresholds.review))
    return LevelResult(
        level=level,
        threshold=threshold,
        leakage=leakage,
        key_overlap=overlaps,
        permutation=permutation,
        reconstructed=reconstructed,
        cohesion=cohesions,
        chained_sources=chained,
    )


def percolation_rows(graphs: Sequence[SourceGraphs]) -> list[PercolationRow]:
    rows: list[PercolationRow] = []
    for g in graphs:
        has_splits = bool((g.view.splits >= 0).any())
        for threshold in sorted(g.labels):
            labels = g.labels[threshold]
            groups = multi_member_groups(labels)
            sizes = [len(group.members) for group in groups]
            crossing_groups, affected = crossing(labels, g.view.splits)
            rows.append(
                PercolationRow(
                    source=g.view.source,
                    threshold=threshold,
                    edges=g.admitted[threshold],
                    groups=len(groups),
                    images_in_groups=sum(sizes),
                    largest=max(sizes, default=1),
                    groups_crossing_any=crossing_groups if has_splits else None,
                    affected_images=affected if has_splits else None,
                )
            )
    return rows


def stability_rows(
    graphs: Sequence[SourceGraphs], thresholds: Thresholds, delta: float
) -> list[Stability]:
    family = thresholds.family
    rows: list[Stability] = []
    for g in graphs:
        for low, high in ((_r(family - delta), family), (family, _r(min(family + delta, 1.0)))):
            if low not in g.labels or high not in g.labels:
                continue
            lab_low, lab_high = g.labels[low], g.labels[high]
            agreement = partition_agreement([int(x) for x in lab_high], [int(x) for x in lab_low])
            rows.append(
                Stability(
                    source=g.view.source,
                    threshold_low=low,
                    threshold_high=high,
                    groups_low=len(multi_member_groups(lab_low)),
                    groups_high=len(multi_member_groups(lab_high)),
                    adjusted_rand=_round(agreement.adjusted_rand),
                    retained_pairs=_round(agreement.pair_recall),
                )
            )
    return rows


@dataclass(frozen=True)
class GlobalGraph:
    edges: Edges  # all pairs over all sources at or above ``family``
    labels: dict[str, NDArray[np.int64]]  # level -> component labels
    rows: list[GroupRow]


def global_graph(features: FeatureSet, thresholds: Thresholds, max_edges: int) -> GlobalGraph:
    edges = collect_edges(features.vectors, thresholds.family, max_edges=max_edges)
    by_threshold = {
        t: lab
        for t, _, lab in sweep_labels(
            len(features.items), edges, [thresholds.near, thresholds.family]
        )
    }
    labels = {"near": by_threshold[thresholds.near], "family": by_threshold[thresholds.family]}
    rows: list[GroupRow] = []
    for level in LEVELS:
        threshold = getattr(thresholds, level)
        rows.extend(
            build_group_rows(
                features.items,
                features.vectors,
                labels[level],
                filter_edges(edges, threshold),
                level=level,
                threshold=threshold,
                prefix=f"VSG-{level}",
            )
        )
    return GlobalGraph(edges, labels, rows)


def group_ids(features: FeatureSet, graph: GlobalGraph) -> dict[str, list[str | None]]:
    """Per level: the id of the multi-member group of every image (``None`` for a singleton)."""
    key_to_row: dict[str, dict[str, str]] = {level: {} for level in LEVELS}
    for row in graph.rows:
        for member in row.members:
            key_to_row[row.level][member] = row.group_id
    keys = [f"{item.source}:{item.item_id}" for item in features.items]
    return {level: [key_to_row[level].get(key) for key in keys] for level in LEVELS}


# ------------------------------------------------------------------------ hash audit


def _sha_codes(features: FeatureSet) -> NDArray[np.int64]:
    return codes([item.sha256 for item in features.items])


def sha_pairs(features: FeatureSet) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
    """All pairs (i < j) with identical bytes."""
    by_sha: dict[str, list[int]] = {}
    for index, item in enumerate(features.items):
        by_sha.setdefault(item.sha256, []).append(index)
    rows, cols = [], []
    for members in by_sha.values():
        for a in range(len(members)):
            for b in range(a + 1, len(members)):
                rows.append(members[a])
                cols.append(members[b])
    return np.array(rows, dtype=np.int64), np.array(cols, dtype=np.int64)


def _key_mix(view: View, i: NDArray[np.int64], j: NDArray[np.int64]) -> tuple[int, int, int] | None:
    if not any(item.group_id for item in view.items):
        return None
    group = codes([item.group_id for item in view.items])
    sub = codes([item.subgroup_id for item in view.items])
    known = (group[i] >= 0) & (group[j] >= 0)
    same_sub = known & (sub[i] >= 0) & (sub[i] == sub[j])
    same_group = known & (group[i] == group[j]) & ~same_sub
    other = known & (group[i] != group[j])
    return int(same_sub.sum()), int(same_group.sum()), int(other.sum())


def _cross_split(
    splits: NDArray[np.int8], i: NDArray[np.int64], j: NDArray[np.int64]
) -> int | None:
    if not (splits >= 0).any():
        return None
    return int(((splits[i] >= 0) & (splits[j] >= 0) & (splits[i] != splits[j])).sum())


def _across_count(a: NDArray[np.uint64], b: NDArray[np.uint64], distance: int) -> int:
    total = 0
    for start in range(0, len(a), 512):
        total += int(np.count_nonzero(hamming_block(a[start : start + 512], b) <= distance))
    return total


def hash_audit(
    features: FeatureSet,
    views: Sequence[View],
    thresholds: Thresholds,
    family_labels: Mapping[str, NDArray[np.int64]],
) -> HashAudit:
    sha_i, _ = sha_pairs(features)
    sha_groups = sum(1 for c in Counter(item.sha256 for item in features.items).values() if c > 1)
    distances = sorted({PHASH_AUTHORS, thresholds.phash_candidate})
    scopes: list[HashScope] = []
    in_family: dict[str, float | None] = {}
    for algorithm in ("phash", "dhash"):
        for distance in distances:
            for view in views:
                hashes = view.phash if algorithm == "phash" else view.dhash
                i, j, _ = pairs_within(hashes, distance)
                mix = _key_mix(view, i, j)
                scopes.append(
                    HashScope(
                        scope=f"within:{view.source}",
                        algorithm=algorithm,
                        distance=distance,
                        pairs=len(i),
                        same_subgroup=None if mix is None else mix[0],
                        same_group_other_subgroup=None if mix is None else mix[1],
                        other_group=None if mix is None else mix[2],
                        cross_split=_cross_split(view.splits, i, j),
                    )
                )
                if algorithm == "phash" and distance == thresholds.phash_candidate:
                    labels = family_labels[view.source]
                    in_family[view.source] = (
                        _r(float((labels[i] == labels[j]).mean())) if len(i) else None
                    )
            for a in range(len(views)):
                for b in range(a + 1, len(views)):
                    first, second = views[a], views[b]
                    ha = first.phash if algorithm == "phash" else first.dhash
                    hb = second.phash if algorithm == "phash" else second.dhash
                    scopes.append(
                        HashScope(
                            scope=f"across:{first.source}|{second.source}",
                            algorithm=algorithm,
                            distance=distance,
                            pairs=_across_count(ha, hb, distance),
                        )
                    )
    return HashAudit(
        sha256_equal_pairs=len(sha_i),
        sha256_equal_groups=sha_groups,
        candidate_distance=thresholds.phash_candidate,
        authors_distance=PHASH_AUTHORS,
        scopes=scopes,
        phash_in_family_group=in_family,
    )


# -------------------------------------------------------------- candidate pairs


@dataclass(frozen=True)
class PairTable:
    """Every candidate pair (i < j) with its measures and the rule's suggested category."""

    i: NDArray[np.int64]
    j: NDArray[np.int64]
    cosine: NDArray[np.float32]
    phash: NDArray[np.uint8]
    dhash: NDArray[np.uint8]
    sha_equal: NDArray[np.bool_]
    category: NDArray[np.int8]  # index into CATEGORIES


def _dot_pairs(
    vectors: NDArray[np.float32], i: NDArray[np.int64], j: NDArray[np.int64]
) -> NDArray[np.float32]:
    out = np.empty(len(i), dtype=np.float32)
    for start in range(0, len(i), 1 << 16):
        a, b = i[start : start + (1 << 16)], j[start : start + (1 << 16)]
        out[start : start + len(a)] = np.einsum("ij,ij->i", vectors[a], vectors[b])
    return out


def candidate_pairs(features: FeatureSet, thresholds: Thresholds, max_edges: int) -> PairTable:
    """Pairs at or above the review cosine, within the pHash candidate distance, or byte-identical."""
    n = len(features.items)
    ci, cj, cs = collect_edges(features.vectors, thresholds.review, max_edges=max_edges)
    hi, hj, _ = pairs_within(features.phash, thresholds.phash_candidate)
    si, sj = sha_pairs(features)
    keys = np.unique(np.concatenate((ci * n + cj, hi * n + hj, si * n + sj)))
    i, j = keys // n, keys % n
    cosine = _dot_pairs(features.vectors, i, j)
    by_key = np.searchsorted(keys, ci * n + cj)
    cosine[by_key] = cs  # the exact block value wherever the scan found the pair
    phash = np.bitwise_count(features.phash[i] ^ features.phash[j]).astype(np.uint8)
    dhash = np.bitwise_count(features.dhash[i] ^ features.dhash[j]).astype(np.uint8)
    sha = _sha_codes(features)
    sha_equal = sha[i] == sha[j]
    category = classify_pairs(cosine, phash, sha_equal, thresholds)
    keep = category >= 0
    return PairTable(
        i[keep], j[keep], cosine[keep], phash[keep], dhash[keep], sha_equal[keep], category[keep]
    )


@dataclass(frozen=True)
class Scopes:
    """Scope of every candidate pair: a source code for a pair inside one source, -1 across sources."""

    names: list[str]  # source names, in code order
    code: NDArray[np.int64]
    cross_split: NDArray[np.bool_]

    def label(self, code: int) -> str:
        return "across" if code < 0 else f"within:{self.names[code]}"


def pair_scopes(features: FeatureSet, i: NDArray[np.int64], j: NDArray[np.int64]) -> Scopes:
    names = sorted({item.source for item in features.items})
    source = np.array([names.index(item.source) for item in features.items], dtype=np.int64)
    splits = split_codes(features.items)
    same = source[i] == source[j]
    cross_split = same & (splits[i] >= 0) & (splits[j] >= 0) & (splits[i] != splits[j])
    return Scopes(names, np.where(same, source[i], -1), cross_split)


def category_counts(features: FeatureSet, pairs: PairTable) -> list[CategoryCount]:
    scopes = pair_scopes(features, pairs.i, pairs.j)
    out: list[CategoryCount] = []
    for code in [*range(len(scopes.names)), -1]:
        in_scope = scopes.code == code
        for index, category in enumerate(CATEGORIES):
            mask = in_scope & (pairs.category == index)
            out.append(
                CategoryCount(
                    scope=scopes.label(code),
                    category=category,
                    pairs=int(mask.sum()),
                    cross_split=int((mask & scopes.cross_split).sum()),
                    cross_source=int(mask.sum()) if code < 0 else 0,
                )
            )
    return out


# -------------------------------------------------------------------- cross-source


def cross_source_summary(
    views: Sequence[View], thresholds: Thresholds, sha_equal_pairs: int, top: int = 10
) -> CrossSourceSummary:
    edges: list[CrossSourceEdges] = []
    best: list[tuple[float, str, str]] = []
    levels = (
        ("review", thresholds.review),
        ("family", thresholds.family),
        ("near", thresholds.near),
    )
    for a in range(len(views)):
        for b in range(a + 1, len(views)):
            first, second = views[a], views[b]
            pairs = {name: 0 for name, _ in levels}
            hit_a = {name: np.zeros(len(first.items), dtype=bool) for name, _ in levels}
            hit_b = {name: np.zeros(len(second.items), dtype=bool) for name, _ in levels}
            for start in range(0, len(first.items), 1024):
                block = first.vectors[start : start + 1024] @ second.vectors.T
                for name, value in levels:
                    mask = block >= np.float32(value)
                    pairs[name] += int(np.count_nonzero(mask))
                    hit_a[name][start : start + len(block)] |= mask.any(axis=1)
                    hit_b[name] |= mask.any(axis=0)
                flat = block.ravel()
                take = min(top, flat.size)
                if take:
                    for position in np.argpartition(-flat, take - 1)[:take].tolist():
                        r, c = divmod(position, block.shape[1])
                        best.append(
                            (
                                float(flat[position]),
                                f"{first.source}:{first.items[start + r].item_id}",
                                f"{second.source}:{second.items[c].item_id}",
                            )
                        )
                best = sorted(best, key=lambda t: (-t[0], t[1], t[2]))[:top]
            for name, _ in levels:
                edges.append(
                    CrossSourceEdges(
                        level=name,
                        source_a=first.source,
                        source_b=second.source,
                        pairs=pairs[name],
                        images_a=int(hit_a[name].sum()),
                        images_b=int(hit_b[name].sum()),
                    )
                )
    return CrossSourceSummary(
        sha256_equal_pairs=sha_equal_pairs,
        edges=edges,
        top_pairs=[(a, b, _r(s)) for s, a, b in best],
    )


# ---------------------------------------------------------------------- review queue


@dataclass(frozen=True)
class ReviewRow:
    pair_id: str
    stratum: str
    i: int
    j: int
    cosine: float
    phash_distance: int
    dhash_distance: int
    machine_category: str  # the rule's suggestion, or BELOW_REVIEW for the control


def control_pairs(
    features: FeatureSet, pairs: PairTable, near: Neighbours, review: float
) -> PairTable:
    """Nearest-neighbour pairs that the rule does not flag: the queue's below-threshold control."""
    n = len(features.items)
    if near.index.shape[1] == 0:
        empty = np.empty(0, dtype=np.int64)
        return PairTable(
            empty,
            empty,
            np.empty(0, np.float32),
            np.empty(0, np.uint8),
            np.empty(0, np.uint8),
            np.empty(0, bool),
            np.empty(0, np.int8),
        )
    a = np.arange(n, dtype=np.int64)
    b = near.index[:, 0]
    keys, first = np.unique(np.minimum(a, b) * n + np.maximum(a, b), return_index=True)
    cosine = near.cosine[first, 0]
    flagged = np.isin(keys, pairs.i * n + pairs.j)
    keep = ~flagged & (cosine < np.float32(review))
    keys, cosine = keys[keep], cosine[keep]
    i, j = keys // n, keys % n
    return PairTable(
        i,
        j,
        cosine,
        np.bitwise_count(features.phash[i] ^ features.phash[j]).astype(np.uint8),
        np.bitwise_count(features.dhash[i] ^ features.dhash[j]).astype(np.uint8),
        np.zeros(len(i), dtype=bool),
        np.full(len(i), -1, dtype=np.int8),
    )


def _stable_seed(text: str) -> int:
    return int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")


def allocate(counts: Mapping[str, int], budget: int) -> dict[str, int]:
    """Equal shares of ``budget`` over the strata; what a small stratum cannot use goes to the others."""
    quota = dict.fromkeys(counts, 0)
    left = budget
    while left > 0:
        open_names = [name for name in sorted(counts) if quota[name] < counts[name]]
        if not open_names:
            break
        share = max(1, left // len(open_names))
        for name in open_names:
            take = min(share, counts[name] - quota[name], left)
            quota[name] += take
            left -= take
            if left == 0:
                break
    return quota


SPLIT_RELATIONS = ("cross-split", "same-split", "no-split")
KEY_RELATIONS = ("same-group", "other-group", "no-key")


def pair_relations(
    features: FeatureSet, i: NDArray[np.int64], j: NDArray[np.int64]
) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
    """Per pair: index into SPLIT_RELATIONS and into KEY_RELATIONS (group_id of the two images)."""
    splits = split_codes(features.items)
    groups = codes(
        [f"{item.source}:{item.group_id}" if item.group_id else None for item in features.items]
    )
    known = (splits[i] >= 0) & (splits[j] >= 0)
    split_rel = np.where(known & (splits[i] != splits[j]), 0, np.where(known, 1, 2))
    keyed = (groups[i] >= 0) & (groups[j] >= 0)
    key_rel = np.where(keyed & (groups[i] == groups[j]), 0, np.where(keyed, 1, 2))
    return split_rel.astype(np.int64), key_rel.astype(np.int64)


def review_queue(
    features: FeatureSet,
    pairs: PairTable,
    near: Neighbours,
    thresholds: Thresholds,
    *,
    budget: int,
    seed: int,
) -> list[ReviewRow]:
    """A seeded queue for a human reviewer, stratified four ways.

    Strata: scope (inside each source, or across sources) x the rule's band (the four categories,
    plus a ``BELOW_REVIEW`` control of nearest neighbours the rule does not flag) x the split
    relation (cross-split, same split, no split) x the metadata relation (same group, other group,
    no key). The budget is shared equally over the strata that hold pairs.
    """
    control = control_pairs(features, pairs, near, thresholds.review)
    tables = {"candidate": pairs, "control": control}
    members: dict[str, tuple[str, NDArray[np.int64]]] = {}
    for kind, table in tables.items():
        scopes = pair_scopes(features, table.i, table.j)
        split_rel, key_rel = pair_relations(features, table.i, table.j)
        band = table.category.astype(np.int64)  # -1 for the control
        code = (((scopes.code + 1) * 5 + (band + 1)) * 3 + split_rel) * 3 + key_rel
        for value in np.unique(code).tolist():
            rows = np.flatnonzero(code == value)
            first = int(rows[0])
            label = CATEGORIES[int(band[first])] if band[first] >= 0 else CONTROL
            name = "|".join(
                [
                    scopes.label(int(scopes.code[first])),
                    label,
                    SPLIT_RELATIONS[int(split_rel[first])],
                    KEY_RELATIONS[int(key_rel[first])],
                ]
            )
            members[name] = (kind, rows)
    quota = allocate({name: len(rows) for name, (_, rows) in members.items()}, budget)
    chosen: list[tuple[str, str, int]] = []
    for name in sorted(members):
        kind, rows = members[name]
        rng = np.random.default_rng(_stable_seed(f"review:{seed}:{name}"))
        picks = rows[np.sort(rng.choice(len(rows), size=quota[name], replace=False))]
        chosen.extend((name, kind, int(row)) for row in picks.tolist())
    chosen.sort(key=lambda c: (c[0], -float(tables[c[1]].cosine[c[2]]), c[2]))
    out: list[ReviewRow] = []
    for number, (name, kind, row) in enumerate(chosen, start=1):
        table = tables[kind]
        out.append(
            ReviewRow(
                pair_id=f"R-{number:04d}",
                stratum=name,
                i=int(table.i[row]),
                j=int(table.j[row]),
                cosine=_r(table.cosine[row]),
                phash_distance=int(table.phash[row]),
                dhash_distance=int(table.dhash[row]),
                machine_category=name.split("|")[1],
            )
        )
    return out


# --------------------------------------------------------------------------- run info


def _long_sides(items: Sequence[ImageItem]) -> NDArray[np.int64]:
    """The longer side of every image whose size ingest recorded, in pixels."""
    return np.array(
        [max(item.width, item.height) for item in items if item.width and item.height],
        dtype=np.int64,
    )


def run_info(
    features: FeatureSet,
    skipped: Sequence[Unreadable],
    spec: EmbedderSpec,
    weights_sha256: str,
    settings: Settings,
) -> RunInfo:
    failures = [
        FailureInfo(source=f.source, item_id=f.item_id, stage=f.stage, error=f.error)
        for f in features.failures
    ] + [
        FailureInfo(source=s.source, item_id=s.item_id, stage=s.stage, error=s.error)
        for s in skipped
    ]
    sources = sorted({item.source for item in features.items} | {f.source for f in failures})
    counts: list[SourceCounts] = []
    for source in sources:
        own = [item for item in features.items if item.source == source]
        failed = sum(1 for f in failures if f.source == source)
        splits = Counter(item.split or "none" for item in own)
        counts.append(
            SourceCounts(
                source=source,
                images=len(own) + failed,
                annotations=sum(item.n_annotations for item in own),
                embedded=len(own),
                failed=failed,
                splits={name: splits[name] for name in [*SPLITS, "none"] if splits[name]},
                group_key=settings.key_names.get(source, GENERIC_KEYS)[0]
                if any(item.group_id for item in own)
                else None,
                acquisition_id=settings.acquisition.get(source),
                median_long_side=int(np.median(sides)) if len(sides := _long_sides(own)) else None,
                max_long_side=int(sides.max()) if len(sides) else None,
            )
        )
    return RunInfo(
        model_name=spec.name,
        model_id=spec.model_id,
        revision=spec.revision,
        weights_sha256=weights_sha256,
        preprocessing_version=spec.preprocessing_version,
        backend=spec.backend,
        dim=spec.dim,
        phash_version=PHASH_VERSION,
        images=len(features.items) + len(failures),
        sources=counts,
        failures=failures,
        skipped_at_ingest=len(skipped),
    )


# ------------------------------------------------------------------------ the run


@dataclass(frozen=True)
class AnalysisResult:
    audit: Audit
    pairs: PairTable
    neighbours: Neighbours
    group_rows: list[GroupRow]
    group_ids: dict[str, list[str | None]]
    review: list[ReviewRow]
    notes: list[str]
    source_labels: dict[tuple[str, str], NDArray[np.int64]] = field(default_factory=dict)
    item_keys: list[tuple[str, str]] = field(default_factory=list)


def run_analysis(
    features: FeatureSet,
    synthetic: Sequence[SyntheticPair],
    *,
    spec: EmbedderSpec,
    weights_sha256: str,
    skipped: Sequence[Unreadable] = (),
    settings: Settings | None = None,
    timings: list[StageTiming] | None = None,
) -> AnalysisResult:
    """The whole audit on features that are already computed (no model, no image decoding)."""
    settings = settings or Settings()
    sink = timings if timings is not None else []
    if len(features.items) < 2:
        raise AnalysisError("the audit needs at least two images with features")
    views = make_views(features)
    with timed("calibration", sink):
        pools = calibration_pools(views, settings)
        curves = [
            PoolCurve(p.view.source, p.spec.name, p.spec.used_in_rule, p.curve) for p in pools
        ]
        thresholds = select_thresholds(curves, synthetic, model=spec.name)
        pool_results = [pool_result(p, thresholds, settings) for p in pools]
    with timed("nearest neighbours", sink):
        near = neighbours(features, views, settings.top_k)
    notes = list(thresholds.notes)
    with timed("graphs and leakage", sink):
        grid = sweep_grid(thresholds, settings.stability_delta)
        graphs = [
            source_graphs(view, grid, settings.max_edges, protected=thresholds.family)
            for view in views
        ]
        notes.extend(g.note for g in graphs if g.note)
        levels = [
            level_result(level, getattr(thresholds, level), graphs, thresholds, settings)
            for level in LEVELS
        ]
        percolation = percolation_rows(graphs)
        stability = stability_rows(graphs, thresholds, settings.stability_delta)
    with timed("global groups", sink):
        graph = global_graph(features, thresholds, settings.max_edges)
        ids = group_ids(features, graph)
    with timed("hash audit", sink):
        hashes = hash_audit(
            features,
            views,
            thresholds,
            {g.view.source: g.labels[thresholds.family] for g in graphs},
        )
    with timed("candidate pairs", sink):
        pairs = candidate_pairs(features, thresholds, settings.max_edges)
        categories = category_counts(features, pairs)
        cross = cross_source_summary(views, thresholds, _cross_sha(features))
        review = review_queue(
            features, pairs, near, thresholds, budget=settings.review_budget, seed=settings.seed
        )
    audit = Audit(
        run=run_info(features, skipped, spec, weights_sha256, settings),
        thresholds=thresholds,
        hash_audit=hashes,
        top1=top1_stats(features, views, near, thresholds),
        pools=pool_results,
        synthetic=synthetic_summary(synthetic, thresholds, settings.seed),
        categories=categories,
        levels=levels,
        percolation=percolation,
        cross_source=cross,
        stability=stability,
        transfer=transfer_rows(views, near, thresholds, settings),
        synthetic_recall=synthetic_recall(synthetic, thresholds),
        metadata_integrity=metadata_integrity(views, settings),
    )
    labels = {
        (g.view.source, level): g.labels[getattr(thresholds, level)]
        for g in graphs
        for level in LEVELS
    }
    keys = [item.key for item in features.items]
    return AnalysisResult(audit, pairs, near, graph.rows, ids, review, notes, labels, keys)


def permutation_reading(baseline: PermutationBaseline | None) -> str | None:
    """The random-split baseline in words (p <= 0.05 on either side, as in the report)."""
    if baseline is None:
        return None
    if baseline.p_upper <= 0.05:
        return "more than random"
    if baseline.p_lower <= 0.05:
        return "fewer than random"
    return "consistent with random"


def _exposed(leak: SourceLeakage) -> float | None:
    images = sum(n.images for n in leak.eval_neighbour)
    return _r(sum(n.with_train_neighbour for n in leak.eval_neighbour) / images) if images else None


def robustness(primary: AnalysisResult, other: AnalysisResult, *, other_model: str) -> Robustness:
    """Compare two audits of the same images made with two representations, each at its own rule."""
    if primary.item_keys != other.item_keys:
        raise AnalysisError("the two audits do not cover the same images in the same order")
    rows: list[RobustnessRow] = []
    for level in LEVELS:
        first = next(x for x in primary.audit.levels if x.level == level)
        second = next(x for x in other.audit.levels if x.level == level)
        for leak in first.leakage:
            twin = next(x for x in second.leakage if x.source == leak.source)
            agreement = partition_agreement(
                [int(x) for x in other.source_labels[(leak.source, level)]],
                [int(x) for x in primary.source_labels[(leak.source, level)]],
            )
            rows.append(
                RobustnessRow(
                    source=leak.source,
                    level=level,
                    threshold_primary=first.threshold,
                    threshold_other=second.threshold,
                    groups_primary=leak.groups,
                    groups_other=twin.groups,
                    crossing_primary=leak.groups_crossing_any if leak.has_splits else None,
                    crossing_other=twin.groups_crossing_any if twin.has_splits else None,
                    affected_primary=leak.affected_images if leak.has_splits else None,
                    affected_other=twin.affected_images if twin.has_splits else None,
                    exposed_primary=_exposed(leak),
                    exposed_other=_exposed(twin),
                    reading_primary=permutation_reading(first.permutation.get(leak.source)),
                    reading_other=permutation_reading(second.permutation.get(leak.source)),
                    adjusted_rand=_round(agreement.adjusted_rand),
                    pair_precision=_round(agreement.pair_precision),
                    pair_recall=_round(agreement.pair_recall),
                )
            )
    top1: dict[str, float] = {}
    for source, index in primary.neighbours.within_index.items():
        twin_index = other.neighbours.within_index[source]
        if len(index):
            top1[source] = _r(float((index == twin_index).mean()))
    return Robustness(
        other_model=other_model,
        other_thresholds=other.audit.thresholds,
        rows=rows,
        top1_agreement=top1,
        other_synthetic_recall=other.audit.synthetic_recall,
        note=(
            "Each representation is calibrated by the same frozen rule (its own pools and "
            "synthetic copies); partitions are compared image by image inside each source."
        ),
    )


def _cross_sha(features: FeatureSet) -> int:
    i, j = sha_pairs(features)
    return sum(
        1
        for a, b in zip(i.tolist(), j.tolist(), strict=True)
        if features.items[a].source != features.items[b].source
    )
