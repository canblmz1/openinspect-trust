"""The results of the audit as validated, serialisable models (M3J).

The four reports are rendered from these models, and the committed JSON is what the integration
tests check the Markdown against.
"""

from __future__ import annotations

from pydantic import Field

from openinspect.dedup.leakage import (
    KeyOverlap,
    PermutationBaseline,
    Reconstructed,
    SourceLeakage,
)
from openinspect.dedup.metrics import Quantiles
from openinspect.dedup.thresholds import Thresholds
from openinspect.provenance.schema import StrictModel

SCHEMA_VERSION = 1


class FailureInfo(StrictModel):
    source: str
    item_id: str
    stage: str
    error: str


class SourceCounts(StrictModel):
    source: str
    images: int
    annotations: int
    embedded: int  # images that have a vector
    failed: int
    splits: dict[str, int]
    group_key: str | None  # what the source's own key is, if any


class RunInfo(StrictModel):
    schema_version: int = SCHEMA_VERSION
    model_name: str
    model_id: str
    revision: str
    weights_sha256: str
    preprocessing_version: str
    backend: str
    dim: int
    phash_version: str
    images: int
    sources: list[SourceCounts]
    failures: list[FailureInfo]
    skipped_at_ingest: int


class StageTimingInfo(StrictModel):
    stage: str
    seconds: float
    peak_ram_bytes: int | None
    images: int | None = None
    note: str | None = None


class Performance(StrictModel):
    stages: list[StageTimingInfo]
    total_seconds: float
    embed_images_per_second: float | None
    embed_model_images_per_second: float | None
    cache_files: int
    cache_bytes: int
    cache_logical_bytes: int
    peak_ram_bytes: int | None
    cpu: str | None = None
    note: str | None = None


# ------------------------------------------------------------------------------ hash audit


class HashScope(StrictModel):
    """Pairs within a hash distance, for one scope (inside a source, or between two sources)."""

    scope: str
    algorithm: str  # phash | dhash
    distance: int
    pairs: int
    same_subgroup: int | None = None
    same_group_other_subgroup: int | None = None
    other_group: int | None = None
    cross_split: int | None = None


class HashAudit(StrictModel):
    sha256_equal_pairs: int
    sha256_equal_groups: int
    candidate_distance: int
    authors_distance: int
    scopes: list[HashScope]
    phash_in_family_group: dict[str, float | None] = Field(
        description="per source: share of pHash-candidate pairs whose two images share a family-level group"
    )


class Top1Stats(StrictModel):
    source: str
    images: int
    within_source: Quantiles | None  # cosine to the most similar other image of the same source
    share_review: float | None
    share_family: float | None
    share_near: float | None
    nearest_is_other_source: int  # images whose most similar image of all is in another source
    other_source_family: int  # ... and at or above the family threshold


# -------------------------------------------------------------------------- calibration


class GridPoint(StrictModel):
    threshold: float
    precision: float | None
    recall: float | None
    f1: float | None
    fpr: float | None
    pairs_above: int


class BaselineCurve(StrictModel):
    name: str  # phash | dhash
    auc: float | None
    average_precision: float | None
    best_f1: float | None
    best_distance: int | None


class Interval(StrictModel):
    low: float
    high: float


class PoolResult(StrictModel):
    source: str
    pool: str
    used_in_rule: bool
    images: int
    positives: int
    negatives: int
    auc: float | None
    auc_ci: Interval | None
    average_precision: float | None
    average_precision_ci: Interval | None
    at_thresholds: dict[str, GridPoint]  # review / family / near
    precision_ci_at_family: Interval | None
    recall_ci_at_family: Interval | None
    grid: list[GridPoint]
    roc: list[tuple[float, float]]  # (false positive rate, true positive rate)
    pr: list[tuple[float, float]]  # (recall, precision)
    histogram: list[tuple[float, float, float]]  # (cosine, positive density, negative density)
    baselines: list[BaselineCurve]


class TransformSummary(StrictModel):
    transform: str
    kind: str
    near_duplicate: bool
    n: int
    cosine: Quantiles
    phash_p95: float
    share_near: float  # share of copies at or above the near threshold


class SyntheticSummary(StrictModel):
    sample_per_source: int
    seed: int
    by_transform: list[TransformSummary]
    by_source: list[TransformSummary]  # the near-duplicate set, per source (kind column = source)


class TransferRow(StrictModel):
    source: str
    labelled: bool
    top1: Quantiles | None
    share_review: float | None
    share_family: float | None
    share_near: float | None


# ------------------------------------------------------------------------------- pairs


class CategoryCount(StrictModel):
    scope: str  # within:<source> | across
    category: str
    pairs: int
    cross_split: int
    cross_source: int


class PercolationRow(StrictModel):
    source: str
    threshold: float
    edges: int
    groups: int
    images_in_groups: int
    largest: int
    groups_crossing_any: int | None
    affected_images: int | None


class Cohesion(StrictModel):
    """How tight the groups of one source are (chaining shows as a low minimum pairwise cosine)."""

    source: str
    level: str
    groups: int
    min_pairwise: Quantiles | None
    mean_pairwise: Quantiles | None
    sizes: Quantiles | None
    share_below_review: (
        float | None
    )  # groups whose weakest member pair is under the review threshold


class Stability(StrictModel):
    source: str
    threshold_low: float
    threshold_high: float
    groups_low: int
    groups_high: int
    adjusted_rand: float | None
    retained_pairs: (
        float | None
    )  # share of the pairs grouped at the lower threshold still grouped at the higher


class LevelResult(StrictModel):
    level: str
    threshold: float
    leakage: list[SourceLeakage]
    key_overlap: list[KeyOverlap]
    permutation: dict[str, PermutationBaseline | None]
    reconstructed: dict[str, Reconstructed | None]
    cohesion: list[Cohesion]
    chained_sources: list[str]  # largest group holds more than 25% of the source's images


class CrossSourceEdges(StrictModel):
    level: str
    source_a: str
    source_b: str
    pairs: int
    images_a: int
    images_b: int


class CrossSourceSummary(StrictModel):
    sha256_equal_pairs: int
    edges: list[CrossSourceEdges]
    top_pairs: list[tuple[str, str, float]]  # (image a, image b, cosine), most similar first


class RobustnessRow(StrictModel):
    source: str
    level: str
    groups_primary: int
    groups_other: int
    crossing_primary: int | None
    crossing_other: int | None
    adjusted_rand: float | None


class Robustness(StrictModel):
    other_model: str
    other_thresholds: Thresholds
    rows: list[RobustnessRow]
    note: str


class Audit(StrictModel):
    """Everything the four reports need."""

    schema_version: int = SCHEMA_VERSION
    run: RunInfo
    thresholds: Thresholds
    hash_audit: HashAudit
    top1: list[Top1Stats]
    pools: list[PoolResult]
    synthetic: SyntheticSummary | None
    categories: list[CategoryCount]
    levels: list[LevelResult]
    percolation: list[PercolationRow]
    cross_source: CrossSourceSummary
    stability: list[Stability]
    transfer: list[TransferRow]
    performance: Performance | None = None
    robustness: Robustness | None = None
    artifacts: dict[str, str] = Field(default_factory=dict)  # file name -> SHA-256
