from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from openinspect.dedup.calibrate import NBINS, bin_of, curve_from_histograms
from openinspect.dedup.synthetic import SyntheticPair
from openinspect.dedup.thresholds import (
    CATEGORIES,
    PHASH_CAP,
    CalibrationError,
    PoolCurve,
    SourceThreshold,
    Thresholds,
    classify_pairs,
    select_thresholds,
)


def pool_curve(
    source: str, *, pure_above: float, noisy_below: float, used: bool = True
) -> PoolCurve:
    """Positives only above ``pure_above``; a positive and a negative mix down to ``noisy_below``."""
    pos = np.zeros(NBINS, dtype=np.int64)
    neg = np.zeros(NBINS, dtype=np.int64)
    pos[bin_of(pure_above) : bin_of(pure_above) + 10] = 20
    pos[bin_of(noisy_below) : bin_of(pure_above)] = 1
    neg[bin_of(noisy_below) : bin_of(pure_above)] = 1
    neg[: bin_of(noisy_below)] = 50
    return PoolCurve(source, f"{source} pool", used, curve_from_histograms(pos, neg))


def synthetic(source: str, near: float, phash: int) -> list[SyntheticPair]:
    rows = []
    for k in range(40):
        rows.append(
            SyntheticPair(
                source,
                f"i{k}",
                "a" * 64,
                "jpeg_q75",
                "photometric",
                True,
                near + 0.01 * (k % 5),
                phash,
                0,
            )
        )
        rows.append(
            SyntheticPair(
                source, f"i{k}", "a" * 64, "crop_90", "geometric", True, near + 0.02, 30, 0
            )
        )
        rows.append(
            SyntheticPair(source, f"i{k}", "a" * 64, "crop_80", "partial", False, 0.1, 40, 0)
        )
    return rows


def test_the_rule_takes_the_strictest_threshold_over_the_labelled_sources() -> None:
    curves = [
        pool_curve("a", pure_above=0.90, noisy_below=0.70),
        pool_curve("b", pure_above=0.94, noisy_below=0.60),
        pool_curve("c", pure_above=0.50, noisy_below=0.30, used=False),  # informational only
    ]
    result = select_thresholds(
        curves, synthetic("a", 0.93, 4) + synthetic("b", 0.96, 6), model="stub"
    )
    by_pool = {p.source: p for p in result.from_pools}
    assert by_pool["a"].family is not None
    assert by_pool["b"].family is not None
    assert result.family == pytest.approx(max(by_pool["a"].family, by_pool["b"].family), abs=1e-6)
    assert result.review <= result.family <= result.near
    assert by_pool["c"].used_in_rule is False
    assert result.family >= 0.9  # the informational pool did not lower it


def test_the_near_duplicate_threshold_keeps_95_percent_of_the_synthetic_copies_in_every_source() -> (
    None
):
    curves = [pool_curve("a", pure_above=0.85, noisy_below=0.6)]
    result = select_thresholds(
        curves, synthetic("a", 0.93, 5) + synthetic("b", 0.97, 7), model="stub"
    )
    assert result.near >= result.family
    smallest = min(s.near for s in result.from_synthetic)
    assert result.near == pytest.approx(max(result.family, smallest), abs=1e-6)
    assert {s.source for s in result.from_synthetic} == {"a", "b"}
    assert (
        result.phash_candidate == 7
    )  # the largest per-source 95th percentile of photometric distances


def test_the_near_threshold_never_drops_below_the_family_threshold() -> None:
    curves = [pool_curve("a", pure_above=0.97, noisy_below=0.8)]
    result = select_thresholds(curves, synthetic("a", 0.60, 3), model="stub")
    assert result.near == result.family


def test_the_phash_candidate_distance_is_capped() -> None:
    curves = [pool_curve("a", pure_above=0.9, noisy_below=0.7)]
    result = select_thresholds(curves, synthetic("a", 0.93, 30), model="stub")
    assert result.phash_candidate == PHASH_CAP
    assert any("capped" in note for note in result.notes)


def test_without_synthetic_positives_the_authors_distance_and_the_family_threshold_are_used() -> (
    None
):
    result = select_thresholds([pool_curve("a", pure_above=0.9, noisy_below=0.7)], [], model="stub")
    assert result.near == result.family
    assert result.phash_candidate == result.phash_authors == 3
    assert result.from_synthetic == []
    assert result.notes


def test_an_unreachable_precision_target_falls_back_to_the_f1_optimum_and_says_so() -> None:
    pos = np.zeros(NBINS, dtype=np.int64)
    neg = np.zeros(NBINS, dtype=np.int64)
    pos[bin_of(0.8) : bin_of(0.8) + 10] = 100
    neg[bin_of(0.8) : bin_of(0.8) + 10] = 300  # precision 0.25 everywhere
    result = select_thresholds(
        [PoolCurve("a", "a pool", True, curve_from_histograms(pos, neg))], [], model="stub"
    )
    (pool,) = result.from_pools
    assert pool.fallback is not None
    assert "F1" in pool.fallback
    assert pool.family == pool.f1_optimal


def test_no_usable_pool_is_an_error() -> None:
    flat = np.zeros(NBINS, dtype=np.int64)
    with pytest.raises(CalibrationError, match="no labelled pool"):
        select_thresholds(
            [PoolCurve("a", "p", True, curve_from_histograms(flat, flat))], [], model="m"
        )
    with pytest.raises(CalibrationError):
        select_thresholds(
            [pool_curve("a", pure_above=0.9, noisy_below=0.7, used=False)], [], model="m"
        )


def test_thresholds_must_be_ordered() -> None:
    kwargs = {"model": "m", "phash_candidate": 5, "from_pools": [], "from_synthetic": []}
    Thresholds(review=0.7, family=0.8, near=0.9, **kwargs)  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="review <= family <= near"):
        Thresholds(review=0.9, family=0.8, near=0.95, **kwargs)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        Thresholds(review=0.7, family=0.8, near=1.5, **kwargs)  # type: ignore[arg-type]


def test_the_pool_record_keeps_its_fields() -> None:
    record = SourceThreshold(
        source="a", pool="p", used_in_rule=True, review=0.6, family=0.8, f1_optimal=0.7
    )
    assert record.fallback is None


def thresholds() -> Thresholds:
    return Thresholds(
        model="m",
        review=0.70,
        family=0.80,
        near=0.90,
        phash_candidate=6,
        from_pools=[],
        from_synthetic=[],
    )


def test_pairs_are_classified_by_similarity_and_hash_evidence() -> None:
    cosine = np.array([0.99, 0.95, 0.85, 0.75, 0.50, 0.50, 0.95, 0.85], dtype=np.float64)
    phash = np.array([0, 40, 40, 40, 40, 3, 2, 2], dtype=np.int64)
    exact = np.array([False, False, False, False, False, False, False, True])
    out = classify_pairs(cosine, phash, exact, thresholds())
    names = [CATEGORIES[i] if i >= 0 else None for i in out.tolist()]
    assert names == [
        "NEAR_DUPLICATE",
        "NEAR_DUPLICATE",
        "SAME_FAMILY_OR_SCENE",
        "REVIEW_REQUIRED",
        None,  # too dissimilar and no hash evidence: not a candidate
        "REVIEW_REQUIRED",  # the hash says near, the embedding disagrees: a human decides
        "NEAR_DUPLICATE",
        "EXACT_DUPLICATE",  # identical bytes are certain whatever the similarity
    ]


def test_category_names_are_the_four_review_classes() -> None:
    assert CATEGORIES == (
        "EXACT_DUPLICATE",
        "NEAR_DUPLICATE",
        "SAME_FAMILY_OR_SCENE",
        "REVIEW_REQUIRED",
    )
