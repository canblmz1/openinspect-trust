"""Threshold calibration against pairs whose group membership is known (M3D).

A *pool* says which pairs of a source are positives and which are negatives:

* positive: both images have the same positive group code (for example the same batch and side);
* negative: both images have a known negative-group code and the codes differ (another batch);
* every other pair is ignored (the label is ambiguous).

All pairs of a source are counted exactly, streamed in blocks into histograms of the similarity, so
ROC, precision, recall and F1 are computed over the whole population of pairs and not over a
sample. Pair labels are noisy in both directions (two images of one batch can look nothing alike;
two batches can carry the same design), which is why the report calls them *group-label
agreement*, not accuracy.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from openinspect.dedup.hashing import hamming_block
from openinspect.dedup.similarity import DEFAULT_CHUNK, iter_upper_blocks

NBINS = 4000  # cosine in [-1, 1], bin width 0.0005
# Fine bins per bootstrap bin: 1, so an interval refers to the same threshold as its estimate.
COARSE = 1

# The selection rule (frozen before any leakage number was computed; docs/M3_PROTOCOL.md).
PRECISION_REVIEW = 0.50
PRECISION_FAMILY = 0.90
MIN_PAIRS = 50
SYNTHETIC_RECALL = 0.95


def codes(values: Sequence[str | None]) -> NDArray[np.int64]:
    """Integer code per value (in order of first appearance); ``-1`` for a missing value."""
    mapping: dict[str, int] = {}
    out = np.empty(len(values), dtype=np.int64)
    for index, value in enumerate(values):
        out[index] = -1 if value is None else mapping.setdefault(value, len(mapping))
    return out


@dataclass(frozen=True)
class Pool:
    """Which pairs of one source are positives and negatives."""

    name: str
    positive: NDArray[np.int64]  # code of the positive group per image, -1 when unknown
    negative: NDArray[np.int64]  # code of the group that separates negatives, -1 when unknown


def label_block(
    pool: Pool, start: int, rows: int, cols_from: int, cols: int
) -> tuple[NDArray[np.bool_], NDArray[np.bool_]]:
    """Positive and negative masks of the pairs (start + r, cols_from + c)."""
    p_rows = pool.positive[start : start + rows, None]
    p_cols = pool.positive[None, cols_from : cols_from + cols]
    n_rows = pool.negative[start : start + rows, None]
    n_cols = pool.negative[None, cols_from : cols_from + cols]
    positive = (p_rows >= 0) & (p_rows == p_cols)
    negative = (n_rows >= 0) & (n_cols >= 0) & (n_rows != n_cols)
    return positive, negative


@dataclass(frozen=True)
class Histograms:
    positive: NDArray[np.int64]  # (NBINS,)
    negative: NDArray[np.int64]
    group_positive: NDArray[np.int64]  # (groups, NBINS // COARSE): positives per positive group


def _bins(sims: NDArray[np.float32]) -> NDArray[np.int64]:
    scaled = np.floor((sims.astype(np.float64) + 1.0) * (NBINS / 2.0)).astype(np.int64)
    return np.clip(scaled, 0, NBINS - 1)


def pool_histograms(
    vectors: NDArray[np.float32], pool: Pool, *, chunk: int = DEFAULT_CHUNK
) -> Histograms:
    """Histogram of the similarity of every positive and every negative pair of the pool."""
    positive = np.zeros(NBINS, dtype=np.int64)
    negative = np.zeros(NBINS, dtype=np.int64)
    n_groups = (
        int(pool.positive.max()) + 1 if len(pool.positive) and pool.positive.max() >= 0 else 0
    )
    group_positive = np.zeros((n_groups, NBINS // COARSE), dtype=np.int64)
    for start, block in iter_upper_blocks(vectors, chunk=chunk):
        rows = block.shape[0]
        pos_mask, neg_mask = label_block(pool, start, rows, start, block.shape[1])
        valid = np.isfinite(block)
        pos_mask &= valid
        neg_mask &= valid
        if pos_mask.any():
            rel_i, rel_j = np.nonzero(pos_mask)
            bins = _bins(block[rel_i, rel_j])
            positive += np.bincount(bins, minlength=NBINS)
            np.add.at(group_positive, (pool.positive[start + rel_i], bins // COARSE), 1)
        if neg_mask.any():
            negative += np.bincount(_bins(block[neg_mask]), minlength=NBINS)
    return Histograms(positive, negative, group_positive)


def hash_pool_histograms(
    hashes: NDArray[np.uint64], pool: Pool, *, chunk: int = 512
) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
    """Histograms of the Hamming distance (0..64) of positive and negative pairs, for the hash baseline."""
    positive = np.zeros(65, dtype=np.int64)
    negative = np.zeros(65, dtype=np.int64)
    n = len(hashes)
    for start in range(0, n, chunk):
        stop = min(start + chunk, n)
        block = hamming_block(hashes[start:stop], hashes[start:])
        rows = np.arange(stop - start)[:, None]
        cols = np.arange(n - start)[None, :]
        upper = cols > rows
        pos_mask, neg_mask = label_block(pool, start, stop - start, start, n - start)
        positive += np.bincount(block[pos_mask & upper], minlength=65)
        negative += np.bincount(block[neg_mask & upper], minlength=65)
    return positive, negative


@dataclass(frozen=True)
class Curve:
    """Cumulative counts from the most similar pairs downwards; index = bin, larger = more similar."""

    tp: NDArray[np.int64]  # positives in this bin or a more similar one
    fp: NDArray[np.int64]  # negatives in this bin or a more similar one
    positives: int
    negatives: int
    pos_hist: NDArray[np.int64]
    neg_hist: NDArray[np.int64]

    @property
    def precision(self) -> NDArray[np.float64]:
        total = (self.tp + self.fp).astype(np.float64)
        ratio = np.divide(self.tp, total, out=np.full(len(total), np.nan), where=total > 0)
        return np.asarray(ratio, dtype=np.float64)

    @property
    def recall(self) -> NDArray[np.float64]:
        return np.asarray(self.tp / max(self.positives, 1), dtype=np.float64)

    @property
    def fpr(self) -> NDArray[np.float64]:
        return np.asarray(self.fp / max(self.negatives, 1), dtype=np.float64)

    @property
    def f1(self) -> NDArray[np.float64]:
        precision = np.nan_to_num(self.precision)
        recall = self.recall
        denom = precision + recall
        score = np.divide(2 * precision * recall, denom, out=np.zeros(len(denom)), where=denom > 0)
        return np.asarray(score, dtype=np.float64)

    @property
    def support(self) -> NDArray[np.int64]:
        return self.tp + self.fp


def curve_from_histograms(pos_hist: NDArray[np.int64], neg_hist: NDArray[np.int64]) -> Curve:
    tp = np.cumsum(pos_hist[::-1])[::-1].astype(np.int64)
    fp = np.cumsum(neg_hist[::-1])[::-1].astype(np.int64)
    return Curve(tp, fp, int(pos_hist.sum()), int(neg_hist.sum()), pos_hist, neg_hist)


def auc(curve: Curve) -> float | None:
    """ROC AUC: P(positive more similar than negative), ties counting one half; ``None`` without both classes."""
    if curve.positives == 0 or curve.negatives == 0:
        return None
    neg_below = np.concatenate(([0], np.cumsum(curve.neg_hist)[:-1]))
    wins = float((curve.pos_hist * (neg_below + 0.5 * curve.neg_hist)).sum())
    return wins / (curve.positives * curve.negatives)


def average_precision(curve: Curve) -> float | None:
    """Average precision: precision weighted by the gain in recall, from the most similar pairs down."""
    if curve.positives == 0:
        return None
    recall = curve.recall
    gain = recall - np.concatenate((recall[1:], [0.0]))
    precision = np.nan_to_num(curve.precision)
    return float((gain * precision).sum())


def bin_of(threshold: float, nbins: int = NBINS) -> int:
    """The bin whose lower edge is the largest one at or below ``threshold``.

    The small offset absorbs rounding: ``threshold_of`` gives decimal edges such as 0.9235 that
    are not exact in binary, and without it about one edge in seven maps to the bin below.
    """
    return int(np.clip(np.floor((threshold + 1.0) * (nbins / 2.0) + 1e-6), 0, nbins - 1))


def threshold_of(bin_index: int, nbins: int = NBINS) -> float:
    return round(-1.0 + bin_index * (2.0 / nbins), 6)


def threshold_at_precision(
    curve: Curve, target: float, *, min_pairs: int = MIN_PAIRS
) -> float | None:
    """Lowest threshold whose precision stays at or above ``target`` from the top of the ranking.

    Thresholds with fewer than ``min_pairs`` pairs above them are too thin to judge and are skipped;
    the first supported threshold that misses the target ends the search. ``None`` if the target is
    never met.
    """
    precision, support = curve.precision, curve.support
    best: int | None = None
    for index in range(len(precision) - 1, -1, -1):
        if support[index] < min_pairs:
            continue
        if precision[index] >= target:
            best = index
        else:
            break
    return None if best is None else threshold_of(best, len(precision))


def f1_optimal_threshold(curve: Curve, *, min_pairs: int = MIN_PAIRS) -> float | None:
    f1 = np.where(curve.support >= min_pairs, curve.f1, -1.0)
    if f1.max() <= 0:
        return None
    # the highest threshold among equals: the stricter choice
    best = int(len(f1) - 1 - np.argmax(f1[::-1]))
    return threshold_of(best, len(f1))


@dataclass(frozen=True)
class PointMetrics:
    threshold: float
    precision: float | None
    recall: float | None
    f1: float | None
    fpr: float | None
    pairs_above: int
    positives_above: int


def metrics_at(curve: Curve, threshold: float) -> PointMetrics:
    index = bin_of(threshold, len(curve.tp))
    tp, fp = int(curve.tp[index]), int(curve.fp[index])
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / curve.positives if curve.positives else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall > 0
        else None
    )
    fpr = fp / curve.negatives if curve.negatives else None
    return PointMetrics(threshold, precision, recall, f1, fpr, tp + fp, tp)


@dataclass(frozen=True)
class Interval:
    low: float
    high: float


def _percentile_interval(values: NDArray[np.float64]) -> Interval | None:
    finite = values[np.isfinite(values)]
    if len(finite) < 10:
        return None
    low, high = np.percentile(finite, [2.5, 97.5])
    return Interval(float(low), float(high))


@dataclass(frozen=True)
class BootstrapResult:
    auc: Interval | None
    average_precision: Interval | None
    precision: Interval | None
    recall: Interval | None


def bootstrap_positive_groups(
    histograms: Histograms, threshold: float, *, resamples: int = 1000, seed: int = 0
) -> BootstrapResult:
    """95% intervals from resampling the positive groups with replacement (negatives stay fixed).

    The positive pairs inside one group are strongly dependent, so the group is the unit of
    resampling. Negative pairs are so numerous that their sampling error is negligible by comparison.
    """
    groups = histograms.group_positive
    if len(groups) < 2:
        return BootstrapResult(None, None, None, None)
    rng = np.random.default_rng(seed)
    neg_coarse = histograms.negative.reshape(-1, COARSE).sum(axis=1)
    weights = rng.multinomial(len(groups), np.full(len(groups), 1.0 / len(groups)), size=resamples)
    # float64 so the product runs in BLAS; the counts stay exact far below 2**53
    pos_boot = weights.astype(np.float64) @ groups.astype(np.float64)  # (resamples, bins)
    coarse_bins = NBINS // COARSE
    target = bin_of(threshold, NBINS) // COARSE
    aucs = np.full(resamples, np.nan)
    aps = np.full(resamples, np.nan)
    precisions = np.full(resamples, np.nan)
    recalls = np.full(resamples, np.nan)
    neg_below = np.concatenate(([0], np.cumsum(neg_coarse)[:-1])).astype(np.float64)
    n_total = float(neg_coarse.sum())
    fp_cum = np.cumsum(neg_coarse[::-1])[::-1].astype(np.float64)
    for index in range(resamples):
        pos = pos_boot[index].astype(np.float64)
        p_total = pos.sum()
        if p_total == 0 or n_total == 0:
            continue
        aucs[index] = float((pos * (neg_below + 0.5 * neg_coarse)).sum() / (p_total * n_total))
        tp_cum = np.cumsum(pos[::-1])[::-1]
        support = tp_cum + fp_cum
        precision = np.divide(tp_cum, support, out=np.zeros(coarse_bins), where=support > 0)
        recall = tp_cum / p_total
        gain = recall - np.concatenate((recall[1:], [0.0]))
        aps[index] = float((gain * precision).sum())
        precisions[index] = precision[target] if support[target] > 0 else np.nan
        recalls[index] = recall[target]
    return BootstrapResult(
        _percentile_interval(aucs),
        _percentile_interval(aps),
        _percentile_interval(precisions),
        _percentile_interval(recalls),
    )


def quantile_threshold(values: NDArray[np.float64], recall: float) -> float:
    """The largest threshold that still keeps ``recall`` of the values at or above it."""
    if len(values) == 0:
        raise ValueError("no values to take a quantile of")
    return float(np.quantile(values, 1.0 - recall, method="lower"))


# ----------------------------------------------------------- sensitivity: both sides


@dataclass(frozen=True)
class PairSample:
    """Every labelled pair of a pool: its bin and the resampling unit of both images.

    The unit is the image's code in the pool's *negative* key (for example the production batch):
    the coarser key, so the positive pairs of a unit and the negative pairs between two units move
    together when units are resampled. ``-1`` means no unit; such an image keeps weight 1.
    """

    pos_bins: NDArray[np.int16]
    pos_a: NDArray[np.int32]
    pos_b: NDArray[np.int32]
    neg_bins: NDArray[np.int16]
    neg_a: NDArray[np.int32]
    neg_b: NDArray[np.int32]
    units: int


def pool_pairs(
    vectors: NDArray[np.float32], pool: Pool, *, chunk: int = DEFAULT_CHUNK
) -> PairSample:
    """The bins and units of every positive and negative pair of the pool (all pairs, exact)."""
    unit = pool.negative.astype(np.int32)
    parts: dict[str, list[NDArray[np.int32]]] = {
        k: [] for k in ("pb", "pa", "pbb", "nb", "na", "nbb")
    }
    for start, block in iter_upper_blocks(vectors, chunk=chunk):
        rows = block.shape[0]
        pos_mask, neg_mask = label_block(pool, start, rows, start, block.shape[1])
        valid = np.isfinite(block)
        for mask, (bins_key, a_key, b_key) in (
            (pos_mask & valid, ("pb", "pa", "pbb")),
            (neg_mask & valid, ("nb", "na", "nbb")),
        ):
            rel_i, rel_j = np.nonzero(mask)
            parts[bins_key].append(_bins(block[rel_i, rel_j]).astype(np.int32))
            parts[a_key].append(unit[start + rel_i])
            parts[b_key].append(unit[start + rel_j])

    def joined(key: str) -> NDArray[np.int32]:
        return np.concatenate(parts[key]) if parts[key] else np.empty(0, dtype=np.int32)

    return PairSample(
        joined("pb").astype(np.int16),
        joined("pa"),
        joined("pbb"),
        joined("nb").astype(np.int16),
        joined("na"),
        joined("nbb"),
        int(unit.max()) + 1 if len(unit) and unit.max() >= 0 else 0,
    )


def bootstrap_both_sides(
    sample: PairSample, threshold: float, *, resamples: int = 1000, seed: int = 0
) -> BootstrapResult:
    """Sensitivity check: resample units with replacement and reweight positives *and* negatives.

    A unit drawn ``w`` times weighs ``w``; a pair inside one unit weighs ``w``, a pair between two
    units the product of their weights. The protocol's interval (:func:`bootstrap_positive_groups`)
    keeps the negatives fixed; comparing the two widths shows whether that choice matters.
    """
    if sample.units < 2:
        return BootstrapResult(None, None, None, None)
    rng = np.random.default_rng(seed)
    target = bin_of(threshold, NBINS)
    aucs = np.full(resamples, np.nan)
    aps = np.full(resamples, np.nan)
    precisions = np.full(resamples, np.nan)
    recalls = np.full(resamples, np.nan)
    same_unit = sample.pos_a == sample.pos_b
    for index in range(resamples):
        weights = rng.multinomial(sample.units, np.full(sample.units, 1.0 / sample.units))
        w = np.append(weights.astype(np.float64), 1.0)  # position -1: no unit, weight 1
        pos_w = np.where(same_unit, w[sample.pos_a], w[sample.pos_a] * w[sample.pos_b])
        neg_w = w[sample.neg_a] * w[sample.neg_b]
        pos = np.rint(np.bincount(sample.pos_bins, weights=pos_w, minlength=NBINS)).astype(np.int64)
        neg = np.rint(np.bincount(sample.neg_bins, weights=neg_w, minlength=NBINS)).astype(np.int64)
        curve = curve_from_histograms(pos, neg)
        if curve.positives == 0 or curve.negatives == 0:
            continue
        value, ap = auc(curve), average_precision(curve)
        aucs[index] = np.nan if value is None else value
        aps[index] = np.nan if ap is None else ap
        support = curve.tp[target] + curve.fp[target]
        precisions[index] = curve.tp[target] / support if support else np.nan
        recalls[index] = curve.tp[target] / curve.positives
    return BootstrapResult(
        _percentile_interval(aucs),
        _percentile_interval(aps),
        _percentile_interval(precisions),
        _percentile_interval(recalls),
    )
