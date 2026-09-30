from __future__ import annotations

import numpy as np
import pytest
from numpy.typing import NDArray

from openinspect.dedup.calibrate import (
    COARSE,
    NBINS,
    BootstrapResult,
    Histograms,
    Interval,
    Pool,
    auc,
    average_precision,
    bin_of,
    bootstrap_both_sides,
    bootstrap_positive_groups,
    codes,
    curve_from_histograms,
    f1_optimal_threshold,
    hash_pool_histograms,
    label_block,
    metrics_at,
    pool_histograms,
    pool_pairs,
    quantile_threshold,
    threshold_at_precision,
    threshold_of,
)


def clusters(
    sizes: list[int], noise: float, dim: int = 6, seed: int = 0
) -> tuple[NDArray[np.float32], list[int]]:
    """Unit vectors in tight clusters around orthogonal centres; also the cluster of each vector."""
    rng = np.random.default_rng(seed)
    rows, label = [], []
    for k, size in enumerate(sizes):
        centre = np.zeros(dim)
        centre[k] = 1.0
        for _ in range(size):
            v = centre + noise * rng.standard_normal(dim)
            rows.append(v / np.linalg.norm(v))
            label.append(k)
    return np.array(rows, dtype=np.float32), label


def brute_auc(sims: list[tuple[float, bool]]) -> float:
    pos = [s for s, is_pos in sims if is_pos]
    neg = [s for s, is_pos in sims if not is_pos]
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def test_codes_number_values_in_order_and_mark_missing() -> None:
    assert codes(["b", None, "a", "b"]).tolist() == [0, -1, 1, 0]
    assert codes([]).tolist() == []


def test_label_block_marks_positives_negatives_and_leaves_the_rest_out() -> None:
    pool = Pool(
        "demo",
        positive=np.array([0, 0, 1, 1, -1], dtype=np.int64),  # (batch, side) of each image
        negative=np.array([0, 0, 0, 1, 1], dtype=np.int64),  # batch of each image
    )
    pos, neg = label_block(pool, 0, 5, 0, 5)
    assert pos[0, 1]  # same (batch, side)
    assert not neg[0, 1]
    assert not pos[0, 2]  # same batch, other side: ambiguous, left out of both
    assert not neg[0, 2]
    assert not pos[0, 3]  # another batch
    assert neg[0, 3]
    assert pos[2, 3]  # positive group 1 (images 2 and 3)
    assert not pos[4, 3]  # an image without a positive group is never positive
    assert not pos[3, 4]


def test_histograms_count_every_labelled_pair() -> None:
    vectors, label = clusters([6, 5, 4], noise=0.05)
    pool = Pool("clusters", np.array(label, dtype=np.int64), np.array(label, dtype=np.int64))
    hist = pool_histograms(vectors, pool, chunk=4)
    assert int(hist.positive.sum()) == 15 + 10 + 6
    assert int(hist.negative.sum()) == 6 * 5 + 6 * 4 + 5 * 4
    assert hist.group_positive.shape == (3, NBINS // COARSE)
    assert int(hist.group_positive.sum()) == int(hist.positive.sum())


def test_perfectly_separated_groups_give_unit_auc_and_precision() -> None:
    vectors, label = clusters([8, 8, 8], noise=0.02)
    pool = Pool("c", np.array(label, dtype=np.int64), np.array(label, dtype=np.int64))
    curve = curve_from_histograms(
        *(lambda h: (h.positive, h.negative))(pool_histograms(vectors, pool))
    )
    assert auc(curve) == pytest.approx(1.0)
    assert average_precision(curve) == pytest.approx(1.0, abs=1e-6)
    point = metrics_at(curve, 0.9)
    assert point.precision == 1.0
    assert point.recall == 1.0
    assert point.fpr == 0.0
    assert point.f1 == 1.0
    assert point.pairs_above == curve.positives


def test_auc_matches_a_brute_force_count_on_overlapping_groups() -> None:
    vectors, label = clusters([10, 10], noise=0.9, dim=4, seed=3)  # heavy overlap
    pool = Pool("c", np.array(label, dtype=np.int64), np.array(label, dtype=np.int64))
    hist = pool_histograms(vectors, pool)
    curve = curve_from_histograms(hist.positive, hist.negative)
    wide = vectors.astype(np.float64)
    pairs = [
        (float(wide[a] @ wide[b]), label[a] == label[b])
        for a in range(20)
        for b in range(a + 1, 20)
    ]
    assert auc(curve) == pytest.approx(brute_auc(pairs), abs=2e-3)
    assert 0.5 < (auc(curve) or 0) < 1.0


def test_random_labels_have_auc_near_one_half() -> None:
    rng = np.random.default_rng(0)
    raw = rng.standard_normal((300, 16))
    vectors = (raw / np.linalg.norm(raw, axis=1, keepdims=True)).astype(np.float32)
    label = rng.integers(0, 6, size=300).astype(np.int64)
    hist = pool_histograms(vectors, Pool("r", label, label))
    assert abs((auc(curve_from_histograms(hist.positive, hist.negative)) or 0) - 0.5) < 0.03


def test_an_undefined_curve_has_no_auc_or_ap() -> None:
    zero = np.zeros(NBINS, dtype=np.int64)
    one = zero.copy()
    one[100] = 5
    assert auc(curve_from_histograms(one, zero)) is None
    assert auc(curve_from_histograms(zero, one)) is None
    assert average_precision(curve_from_histograms(zero, one)) is None


def synthetic_curve() -> tuple[NDArray[np.int64], NDArray[np.int64]]:
    """Positives dominate the top bins; negatives dominate below."""
    pos = np.zeros(NBINS, dtype=np.int64)
    neg = np.zeros(NBINS, dtype=np.int64)
    top = bin_of(0.95)
    pos[top : top + 20] = 10  # 200 positives at about 0.95
    mid = bin_of(0.80)
    pos[mid : mid + 20] = 5  # 100 positives at about 0.80
    neg[mid : mid + 20] = 5  # 100 negatives at about 0.80
    low = bin_of(0.50)
    neg[low : low + 20] = 500
    pos[low : low + 20] = 1
    return pos, neg


def test_threshold_at_precision_stops_where_precision_falls_below_the_target() -> None:
    curve = curve_from_histograms(*synthetic_curve())
    high = threshold_at_precision(curve, 0.95)
    assert high is not None
    at = metrics_at(curve, high)
    assert at.precision is not None
    assert at.precision >= 0.95
    one_bin_lower = metrics_at(curve, high - 0.0005)
    assert one_bin_lower.precision is not None
    assert one_bin_lower.precision < 0.95  # the very next threshold misses the target
    half = threshold_at_precision(curve, 0.5)
    assert half is not None
    # precision stays 0.75 all the way down to the empty gap above the noisy cluster at 0.50
    assert 0.50 < half < 0.52
    assert threshold_of(bin_of(0.8)) == pytest.approx(0.8, abs=0.0006)
    assert threshold_at_precision(curve, 1.01) is None  # never reached


def test_thin_supports_are_not_judged() -> None:
    pos = np.zeros(NBINS, dtype=np.int64)
    neg = np.zeros(NBINS, dtype=np.int64)
    pos[bin_of(0.99)] = 1
    neg[bin_of(0.99)] = 3  # 25% precision on four pairs: too few to judge
    pos[bin_of(0.90)] = 400
    curve = curve_from_histograms(pos, neg)
    assert threshold_at_precision(curve, 0.9, min_pairs=50) is not None
    assert threshold_at_precision(curve, 0.9, min_pairs=1) is None


def test_f1_optimal_threshold_picks_the_best_balance() -> None:
    curve = curve_from_histograms(*synthetic_curve())
    best = f1_optimal_threshold(curve)
    assert best is not None
    assert best == pytest.approx(0.80, abs=0.01)
    flat = np.zeros(NBINS, dtype=np.int64)
    assert f1_optimal_threshold(curve_from_histograms(flat, flat)) is None


def test_bootstrap_is_reproducible_and_brackets_the_estimate() -> None:
    vectors, label = clusters([12, 12, 12, 12], noise=0.6, dim=5, seed=5)
    pool = Pool("c", np.array(label, dtype=np.int64), np.array(label, dtype=np.int64))
    hist = pool_histograms(vectors, pool)
    point = auc(curve_from_histograms(hist.positive, hist.negative)) or 0.0
    first = bootstrap_positive_groups(hist, 0.7, resamples=200, seed=1)
    second = bootstrap_positive_groups(hist, 0.7, resamples=200, seed=1)
    assert first == second
    assert first.auc is not None
    assert first.auc.low <= point + 0.05
    assert first.auc.high >= point - 0.05
    assert first.average_precision is not None
    assert first.recall is not None


def test_bootstrap_needs_two_groups() -> None:
    vectors, label = clusters([10], noise=0.1)
    pool = Pool("c", np.array(label, dtype=np.int64), np.array(label, dtype=np.int64))
    result = bootstrap_positive_groups(pool_histograms(vectors, pool), 0.5, resamples=10)
    assert result.auc is None
    assert result.precision is None


def test_hash_histograms_match_brute_force() -> None:
    rng = np.random.default_rng(2)
    hashes = rng.integers(0, 2**63, size=30, dtype=np.uint64)
    label = np.array([i % 3 for i in range(30)], dtype=np.int64)
    pool = Pool("h", label, label)
    positive, negative = hash_pool_histograms(hashes, pool, chunk=7)
    exp_pos, exp_neg = np.zeros(65, dtype=np.int64), np.zeros(65, dtype=np.int64)
    for a in range(30):
        for b in range(a + 1, 30):
            d = (int(hashes[a]) ^ int(hashes[b])).bit_count()
            if label[a] == label[b]:
                exp_pos[d] += 1
            else:
                exp_neg[d] += 1
    assert positive.tolist() == exp_pos.tolist()
    assert negative.tolist() == exp_neg.tolist()


def test_quantile_threshold_keeps_the_wanted_share_above_it() -> None:
    values = np.arange(100, dtype=np.float64) / 100.0
    threshold = quantile_threshold(values, 0.95)
    assert (values >= threshold).mean() >= 0.95
    assert (values >= threshold + 0.02).mean() < 0.95
    with pytest.raises(ValueError, match="no values"):
        quantile_threshold(np.array([]), 0.95)


def test_every_bin_edge_maps_back_to_its_own_bin() -> None:
    # decimal edges such as 0.9235 are not exact in binary; without care one in seven slips a bin
    assert all(bin_of(threshold_of(b)) == b for b in range(NBINS))


def test_metrics_at_a_bin_edge_count_exactly_the_pairs_at_or_above_it() -> None:
    pos = np.zeros(NBINS, dtype=np.int64)
    neg = np.zeros(NBINS, dtype=np.int64)
    pos[bin_of(0.9235)] = 5
    neg[bin_of(0.9235) - 1] = 7  # just below the threshold: must not count
    point = metrics_at(curve_from_histograms(pos, neg), 0.9235)
    assert point.pairs_above == 5
    assert point.precision == 1.0


def test_bootstrap_intervals_refer_to_the_exact_threshold() -> None:
    threshold = 0.9235
    edge = bin_of(threshold)
    groups = np.zeros((12, NBINS), dtype=np.int64)
    groups[:, edge] = 3  # every positive sits in the threshold's own bin
    negative = np.zeros(NBINS, dtype=np.int64)
    negative[edge - 1] = 1000  # one bin below: outside, however coarse the bootstrap
    histograms = Histograms(groups.sum(axis=0), negative, groups)
    result = bootstrap_positive_groups(histograms, threshold, resamples=200)
    assert result.precision == Interval(1.0, 1.0)
    assert result.recall == Interval(1.0, 1.0)


def test_pool_pairs_hold_exactly_the_pairs_of_the_histograms() -> None:
    vectors, label = clusters([6, 5, 4], noise=0.3, seed=2)
    unit = np.array(label, dtype=np.int64)
    pool = Pool("c", unit, unit)
    hist = pool_histograms(vectors, pool, chunk=4)
    sample = pool_pairs(vectors, pool, chunk=4)
    assert sample.units == 3
    assert np.bincount(sample.pos_bins, minlength=NBINS).tolist() == hist.positive.tolist()
    assert np.bincount(sample.neg_bins, minlength=NBINS).tolist() == hist.negative.tolist()
    assert (sample.pos_a == sample.pos_b).all()  # a positive pair lies inside one unit
    assert (sample.neg_a != sample.neg_b).all()


def test_the_both_sides_bootstrap_is_seeded_and_brackets_the_estimate() -> None:
    vectors, label = clusters([10] * 8, noise=0.7, dim=10, seed=4)
    unit = np.array(label, dtype=np.int64)
    pool = Pool("c", unit, unit)
    sample = pool_pairs(vectors, pool)
    hist = pool_histograms(vectors, pool)
    point = auc(curve_from_histograms(hist.positive, hist.negative)) or 0.0
    first = bootstrap_both_sides(sample, 0.8, resamples=200, seed=3)
    assert first == bootstrap_both_sides(sample, 0.8, resamples=200, seed=3)
    assert first.auc is not None
    assert first.auc.low <= point <= first.auc.high
    assert first.precision is not None
    single = pool_pairs(vectors[:10], Pool("one", unit[:10], unit[:10]))
    assert bootstrap_both_sides(single, 0.8, resamples=50) == BootstrapResult(
        None, None, None, None
    )
