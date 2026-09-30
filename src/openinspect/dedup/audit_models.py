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
    acquisition_id: str | None = None
    median_long_side: int | None = None  # pixels, before the model's resize
    max_long_side: int | None = None


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
    code_commit: str | None = None  # HEAD when the numbers were produced
    code_dirty: bool | None = None  # tracked files differed from HEAD
    seed: int = 0


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
    top1_same_group: float | None = None  # share whose most similar image shares the group key
    top1_same_subgroup: float | None = None
    chance_same_group: float | None = None  # the same for a random other image of the source
    chance_same_subgroup: float | None = None
    cdf: list[tuple[float, float]] = Field(
        default_factory=list
    )  # (cosine, share of images at or below)


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


class UncertaintyCheck(StrictModel):
    """One 95% interval by the protocol's bootstrap and by the both-sides sensitivity check."""

    metric: str
    primary: Interval | None  # positive groups resampled, negative pairs fixed (protocol section 5)
    both_sides: Interval | None  # units of the negative key resampled, weighting both sides
    width_ratio: float | None  # both_sides width / primary width


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
    positive_groups: int | None = None  # resampling units of the protocol's bootstrap
    negative_units: int | None = None  # resampling units of the both-sides check
    uncertainty: list[UncertaintyCheck] = Field(default_factory=list)


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


class SyntheticRecall(StrictModel):
    """How many of a source's synthetic near-duplicates the final near threshold keeps.

    ``near`` is the larger of ``family`` and the lowest per-source value, so the final threshold
    can be stricter than a source's own: its recall is measured here, never assumed.
    """

    source: str
    target_recall: float
    source_threshold: float  # the cosine that keeps the target share of this source's copies
    final_near_threshold: float
    achieved_recall: float  # share of this source's copies at or above the final threshold
    n_pairs: int
    meets_target: bool


class MetadataIntegrity(StrictModel):
    """Whether a source's own proxy key stays inside one split (only sources with a split and a key)."""

    source: str
    key: str  # group_id | subgroup_id
    key_name: str  # what the key means for this source
    values: int  # distinct values among images that have a split
    crossing: int  # values found in two or more splits
    images_in_crossing: int


class SourceProvenance(StrictModel):
    """What the registry and the ingest report say about a source (inputs of the assurance report)."""

    source: str
    licence: str | None
    evidence_files: int
    evidence_ok: bool  # the registry validates the source without an error
    archive_ok: (
        bool | None
    )  # size, repository checksum and zip CRC matched at ingest; None: no report
    images_expected: int | None  # the manifest's image count
    images_recorded: int | None  # images decoded and recorded at ingest
    acquisition_id: str | None


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


class ComponentSummary(StrictModel):
    """One visual similarity component; ``chaining_gap`` = weakest edge - weakest member pair."""

    size: int
    share_of_source: float
    edge_min_similarity: float
    edge_mean_similarity: float
    all_pairs_min_similarity: float
    all_pairs_mean_similarity: float
    chaining_gap: float
    splits: list[str]


class Cohesion(StrictModel):
    """How tight the components of one source are (chaining shows as a low weakest member pair)."""

    source: str
    level: str
    groups: int
    min_pairwise: Quantiles | None
    mean_pairwise: Quantiles | None
    sizes: Quantiles | None
    share_below_review: float | None  # components whose weakest member pair is under review
    chaining_gap: Quantiles | None = None
    largest: list[ComponentSummary] = Field(default_factory=list)  # the five largest, by size


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
    """One source and level under the primary and the second representation, each at its own rule."""

    source: str
    level: str
    threshold_primary: float
    threshold_other: float
    groups_primary: int
    groups_other: int
    crossing_primary: int | None
    crossing_other: int | None
    affected_primary: int | None
    affected_other: int | None
    exposed_primary: float | None  # share of evaluation images with a training image at the level
    exposed_other: float | None
    reading_primary: str | None  # the random-split baseline in words
    reading_other: str | None
    adjusted_rand: float | None  # agreement of the two partitions of the source's images
    pair_precision: float | None  # of the pairs the second groups together, share the primary does
    pair_recall: float | None  # of the pairs the primary groups together, share the second does


class Robustness(StrictModel):
    """Do the leakage conclusions survive a reasonable change of representation? (protocol 9e)"""

    other_model: str
    other_thresholds: Thresholds
    rows: list[RobustnessRow]
    top1_agreement: dict[str, float] = Field(default_factory=dict)  # same most similar image
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
    synthetic_recall: list[SyntheticRecall] = Field(default_factory=list)
    metadata_integrity: list[MetadataIntegrity] = Field(default_factory=list)
    provenance: list[SourceProvenance] = Field(default_factory=list)
    performance: Performance | None = None
    robustness: Robustness | None = None
    artifacts: dict[str, str] = Field(default_factory=dict)  # file name -> SHA-256
