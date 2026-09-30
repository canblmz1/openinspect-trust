"""Choosing the similarity thresholds by an explicit rule, and the pair categories (M3D, M3H).

The rule (frozen in docs/M3_PROTOCOL.md before any leakage number was computed):

* ``review``: the lowest cosine whose precision against the group labels stays at or above 0.50
  (more likely than not the same group), on every labelled source;
* ``family``: the same with precision 0.90;
* ``near``: the larger of ``family`` and the cosine that still keeps 95% of the synthetic
  near-duplicates (an image and its mildly transformed copy) above it, on every source;
* ``phash_candidate``: the Hamming distance that covers 95% of the photometric synthetic copies.

Taking the maximum over the labelled sources means a threshold meets its precision target wherever
it was measured, which is the conservative choice for a source without labels.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Literal

import numpy as np
from numpy.typing import NDArray
from pydantic import Field, model_validator

from openinspect.dedup.calibrate import (
    PRECISION_FAMILY,
    PRECISION_REVIEW,
    SYNTHETIC_RECALL,
    Curve,
    f1_optimal_threshold,
    quantile_threshold,
    threshold_at_precision,
)
from openinspect.dedup.synthetic import SyntheticPair
from openinspect.provenance.schema import StrictModel

RULE_VERSION = "v1"
PHASH_CAP = 12  # the candidate set must stay reviewable
PHASH_AUTHORS = 3  # the PCB-IND authors removed pairs within this distance inside a batch

Category = Literal["EXACT_DUPLICATE", "NEAR_DUPLICATE", "SAME_FAMILY_OR_SCENE", "REVIEW_REQUIRED"]
CATEGORIES: tuple[Category, ...] = (
    "EXACT_DUPLICATE",
    "NEAR_DUPLICATE",
    "SAME_FAMILY_OR_SCENE",
    "REVIEW_REQUIRED",
)


class CalibrationError(Exception):
    """No threshold can be chosen from the available evidence."""


class SourceThreshold(StrictModel):
    """What one labelled pool says about the thresholds."""

    source: str
    pool: str
    used_in_rule: bool
    review: float | None  # lowest cosine with precision >= 0.50
    family: float | None  # lowest cosine with precision >= 0.90
    f1_optimal: float | None
    fallback: str | None = None


class SyntheticThreshold(StrictModel):
    source: str
    near: float  # cosine that keeps 95% of this source's synthetic near-duplicates
    phash: int  # Hamming distance that covers 95% of its photometric copies
    n_near: int
    n_photometric: int


class Thresholds(StrictModel):
    schema_version: int = 1
    model: str
    rule: str = RULE_VERSION
    review: Annotated[float, Field(ge=-1.0, le=1.0)]
    family: Annotated[float, Field(ge=-1.0, le=1.0)]
    near: Annotated[float, Field(ge=-1.0, le=1.0)]
    phash_candidate: Annotated[int, Field(ge=0, le=64)]
    phash_authors: int = PHASH_AUTHORS
    precision_review: float = PRECISION_REVIEW
    precision_family: float = PRECISION_FAMILY
    synthetic_recall: float = SYNTHETIC_RECALL
    from_pools: list[SourceThreshold]
    from_synthetic: list[SyntheticThreshold]
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _ordered(self) -> Thresholds:
        if not self.review <= self.family <= self.near:
            raise ValueError("thresholds must satisfy review <= family <= near")
        return self


@dataclass(frozen=True)
class PoolCurve:
    source: str
    pool: str
    used_in_rule: bool
    curve: Curve


def _synthetic_by_source(
    synthetic: Sequence[SyntheticPair],
) -> list[SyntheticThreshold]:
    out: list[SyntheticThreshold] = []
    for source in sorted({pair.source for pair in synthetic}):
        own = [pair for pair in synthetic if pair.source == source]
        near = np.array([p.cosine for p in own if p.near_duplicate], dtype=np.float64)
        photometric = np.array(
            [p.phash_distance for p in own if p.kind == "photometric"], dtype=np.float64
        )
        if len(near) == 0 or len(photometric) == 0:
            continue
        out.append(
            SyntheticThreshold(
                source=source,
                near=round(quantile_threshold(near, SYNTHETIC_RECALL), 6),
                phash=int(np.quantile(photometric, SYNTHETIC_RECALL, method="higher")),
                n_near=len(near),
                n_photometric=len(photometric),
            )
        )
    return out


def select_thresholds(
    curves: Sequence[PoolCurve], synthetic: Sequence[SyntheticPair], *, model: str
) -> Thresholds:
    """Apply the frozen rule to the calibration curves and the synthetic positives."""
    from_pools: list[SourceThreshold] = []
    for pool_curve in curves:
        review = threshold_at_precision(pool_curve.curve, PRECISION_REVIEW)
        family = threshold_at_precision(pool_curve.curve, PRECISION_FAMILY)
        f1 = f1_optimal_threshold(pool_curve.curve)
        fallback = None
        if family is None:
            family, fallback = f1, "precision 0.90 is never reached: the F1-optimal cosine is used"
        if review is None:
            review = f1 if fallback else family
            fallback = fallback or "precision 0.50 is never reached: the family cosine is used"
        from_pools.append(
            SourceThreshold(
                source=pool_curve.source,
                pool=pool_curve.pool,
                used_in_rule=pool_curve.used_in_rule,
                review=review,
                family=family,
                f1_optimal=f1,
                fallback=fallback,
            )
        )
    ruled = [p for p in from_pools if p.used_in_rule and p.family is not None]
    if not ruled:
        raise CalibrationError("no labelled pool gives a threshold")
    family_value = max(p.family for p in ruled if p.family is not None)
    review_value = min(family_value, max(p.review for p in ruled if p.review is not None))
    by_source = _synthetic_by_source(synthetic)
    notes: list[str] = []
    if by_source:
        synthetic_near = min(s.near for s in by_source)
        phash_value = min(max(s.phash for s in by_source), PHASH_CAP)
        if max(s.phash for s in by_source) > PHASH_CAP:
            notes.append(f"the pHash candidate distance was capped at {PHASH_CAP} bits")
    else:
        synthetic_near = family_value
        phash_value = PHASH_AUTHORS
        notes.append(
            "no synthetic positives: near = family and the pHash distance is the authors' 3"
        )
    return Thresholds(
        model=model,
        review=round(review_value, 6),
        family=round(family_value, 6),
        near=round(max(family_value, synthetic_near), 6),
        phash_candidate=phash_value,
        from_pools=from_pools,
        from_synthetic=by_source,
        notes=notes,
    )


def classify_pairs(
    cosine: NDArray[np.float32] | NDArray[np.float64],
    phash_distance: NDArray[np.uint8] | NDArray[np.int64],
    sha_equal: NDArray[np.bool_],
    thresholds: Thresholds,
) -> NDArray[np.int8]:
    """Category index per pair (into ``CATEGORIES``), or ``-1`` when the pair is not a candidate.

    Only exact duplicates are certain. Near duplicates, same-family pairs and review cases are
    suggestions for a human reviewer, never verdicts.
    """
    result = np.full(len(cosine), -1, dtype=np.int8)
    hash_hint = phash_distance <= thresholds.phash_candidate
    result[(cosine >= thresholds.review) | hash_hint] = CATEGORIES.index("REVIEW_REQUIRED")
    result[cosine >= thresholds.family] = CATEGORIES.index("SAME_FAMILY_OR_SCENE")
    result[cosine >= thresholds.near] = CATEGORIES.index("NEAR_DUPLICATE")
    result[sha_equal] = CATEGORIES.index("EXACT_DUPLICATE")
    return result
