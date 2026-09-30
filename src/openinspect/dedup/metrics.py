"""Agreement between two partitions of the same images (M3F).

Used to ask how well the visual similarity groups line up with a known grouping key (production
batch, design family). ``predicted`` is the partition under test, ``truth`` the key partition.
Pair precision: of the image pairs that share a similarity group, the share that also share a key.
Pair recall: of the pairs that share a key, the share that also share a similarity group.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray
from pydantic import Field

from openinspect.provenance.schema import StrictModel


class PartitionAgreement(StrictModel):
    n_images: int
    pair_precision: float | None
    pair_recall: float | None
    adjusted_rand: float | None
    homogeneity: float | None  # each similarity group holds members of one key
    completeness: float | None  # each key is held by one similarity group
    v_measure: float | None
    multi_member_purity: float | None = Field(
        description="share of members, over groups of two or more, that carry the group's majority key"
    )


def _pairs(n: int) -> int:
    return n * (n - 1) // 2


def partition_agreement(predicted: Sequence[int], truth: Sequence[int]) -> PartitionAgreement:
    """Agreement of two labelings; images with a negative label in either are left out."""
    keep = [i for i, (p, t) in enumerate(zip(predicted, truth, strict=True)) if p >= 0 and t >= 0]
    n = len(keep)
    if n < 2:
        return PartitionAgreement(
            n_images=n,
            pair_precision=None,
            pair_recall=None,
            adjusted_rand=None,
            homogeneity=None,
            completeness=None,
            v_measure=None,
            multi_member_purity=None,
        )
    cells = Counter((predicted[i], truth[i]) for i in keep)
    rows = Counter(predicted[i] for i in keep)
    cols = Counter(truth[i] for i in keep)
    s_ij = sum(_pairs(c) for c in cells.values())
    s_rows = sum(_pairs(c) for c in rows.values())
    s_cols = sum(_pairs(c) for c in cols.values())
    total = _pairs(n)
    precision = s_ij / s_rows if s_rows else None
    recall = s_ij / s_cols if s_cols else None
    expected = s_rows * s_cols / total
    maximum = 0.5 * (s_rows + s_cols)
    ari = 1.0 if maximum == expected else (s_ij - expected) / (maximum - expected)

    def entropy(counter: Counter[int]) -> float:
        return -sum(c / n * math.log(c / n) for c in counter.values())

    h_pred, h_truth = entropy(rows), entropy(cols)
    mutual = sum(c / n * math.log(n * c / (rows[p] * cols[t])) for (p, t), c in cells.items())
    homogeneity = 1.0 if h_truth == 0 else mutual / h_truth
    completeness = 1.0 if h_pred == 0 else mutual / h_pred
    v = (
        0.0
        if homogeneity + completeness == 0
        else 2 * homogeneity * completeness / (homogeneity + completeness)
    )
    members_total = members_majority = 0
    by_group: dict[int, Counter[int]] = {}
    for (p, t), c in cells.items():
        by_group.setdefault(p, Counter())[t] += c
    for counter in by_group.values():
        size = sum(counter.values())
        if size >= 2:
            members_total += size
            members_majority += max(counter.values())
    purity = members_majority / members_total if members_total else None
    return PartitionAgreement(
        n_images=n,
        pair_precision=precision,
        pair_recall=recall,
        adjusted_rand=ari,
        homogeneity=homogeneity,
        completeness=completeness,
        v_measure=v,
        multi_member_purity=purity,
    )


class Quantiles(StrictModel):
    n: int
    minimum: float
    p05: float
    p25: float
    median: float
    p75: float
    p95: float
    p99: float
    maximum: float
    mean: float


def quantiles(values: NDArray[np.float32] | NDArray[np.float64]) -> Quantiles | None:
    if len(values) == 0:
        return None
    v = values.astype(np.float64)
    q = np.quantile(v, [0.05, 0.25, 0.5, 0.75, 0.95, 0.99])
    return Quantiles(
        n=len(v),
        minimum=float(v.min()),
        p05=float(q[0]),
        p25=float(q[1]),
        median=float(q[2]),
        p75=float(q[3]),
        p95=float(q[4]),
        p99=float(q[5]),
        maximum=float(v.max()),
        mean=float(v.mean()),
    )
