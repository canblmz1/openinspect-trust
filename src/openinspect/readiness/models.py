"""The machine-readable result of M5.5: ``artifacts/m5_5/readiness.json``.

Every report of ``reports/m5_5/`` is rendered from this model, and ``openinspect readiness check``
re-derives what it can from committed files and compares.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from openinspect.provenance.schema import StrictModel
from openinspect.readiness.giant import GiantComponent
from openinspect.readiness.labels import LabelSummary
from openinspect.readiness.probe import ProbeResult
from openinspect.readiness.representation import RepresentationResult
from openinspect.release.checks import SplitMeasure

Verdict = Literal[
    "TRAINING READY", "TRAINING READY WITH EXPLICIT LIMITATIONS", "NOT TRAINING READY"
]


class ModelPin(StrictModel):
    name: str
    model_id: str
    revision: str
    weights_sha256: str


class Provenance(StrictModel):
    command: str
    code_commit: str | None
    code_dirty: bool | None
    release: str
    release_manifest_sha256: str
    design_seeds: list[int]
    split_seed: int
    probe_seed: int
    models: list[ModelPin]
    thresholds: dict[str, dict[str, float]]  # model -> family / near
    inputs: dict[str, str]  # committed M3, M4, M5 and M6 files used -> SHA-256
    outputs: dict[str, str]  # files written by this run -> SHA-256


class ReproductionRecord(StrictModel):
    group_keys_match: bool
    schemes_match: dict[str, bool]
    split_files_match: dict[str, bool]
    small_components_match_m3: bool | None  # recomputed from the cache (needs the data directory)


class ConditionSummary(StrictModel):
    name: str  # C0 or C1
    file: str
    sha256: str
    items: dict[str, dict[str, int]]  # split -> source -> items
    boxes: dict[str, dict[str, int]]  # split -> class -> boxes
    measure: SplitMeasure
    exposed_test_items: int  # test items whose constraint group has a training item


class DesignSummary(StrictModel):
    seed: int
    params: dict[str, float | int]
    roles: dict[str, int]
    roles_file: str
    roles_sha256: str
    test_items: int
    probes: dict[str, int]  # source -> exposed test items (in C0)
    probe_links: dict[str, int]  # strongest direct link of a probe to one of its mates
    controls: dict[str, int]  # source -> unexposed test items
    shortfalls: dict[str, dict[str, int]]
    replacements: dict[str, int]  # match kind -> mates
    conditions: list[ConditionSummary]
    train_box_difference: dict[str, int]  # class -> C0 boxes minus C1 boxes in train
    train_items_equal_by_source: bool
    changes: list[str]
    constant: list[str]


class HeldOutSummary(StrictModel):
    fold: str  # held-out source
    regime: Literal["B-strict", "B-natural"]
    file: str
    sha256: str
    items: dict[str, dict[str, int]]
    measure: SplitMeasure
    pure: bool
    test_sources: list[str]
    excluded: int
    linked_training_items: int  # train or val items in a constraint group that has a test item


class EstimandRecord(StrictModel):
    a0_test: dict[str, int]
    a1_test: dict[str, int]
    test_overlap: int  # items in both test sets
    a0_train_holds_a1_test: int  # A1 test items that A0 trains on
    a1_test_without_source: list[str]
    reading: list[str]


class Negatives(StrictModel):
    available: dict[str, int]  # source -> ingested images without a box
    released: int
    excluded_reason: str
    policy: str
    same_in_every_regime: bool
    untested: list[str]


class PairSplitRelation(StrictModel):
    regime: str
    train_test: int
    train_val: int
    val_test: int
    same_split: int
    not_both_assigned: int


class PhashOnlyPairs(StrictModel):
    file: str
    sha256: str
    pairs: int  # pHash-only candidate pairs whose two images are both released
    same_source: int
    cross_source: int
    phash_distance: dict[str, int]
    cosine_small: dict[str, float]  # min / median / max
    cosine_base: dict[str, float]
    relations: list[PairSplitRelation]


class UltralyticsCheck(StrictModel):
    version: str
    ok: bool
    totals: dict[str, int]
    boxes_per_class: dict[str, int]
    messages_total: int
    messages: list[str]


class PackageCheck(StrictModel):
    scheme: str
    package: str
    sha256: str
    bytes: int
    items: dict[str, int]  # split -> images
    boxes: dict[str, int]  # class -> boxes in the archive
    expected_boxes: dict[str, int]
    internal_ok: bool
    internal_rows: int
    internal_problems: dict[str, int]
    internal_examples: list[str]
    internal_overhangs: int  # boxes leaving the image by less than half a pixel (they pass)
    internal_max_overhang_px: float
    ultralytics: UltralyticsCheck | None


class ExportValidation(StrictModel):
    packages: list[PackageCheck]
    independence: list[str]


class Answer(StrictModel):
    number: int
    question: str
    answer: str


class PlanRun(StrictModel):
    run_id: str
    regime: str
    split_file: str
    package: str
    training_seed: int
    purpose: str


class TrainingPlan(StrictModel):
    model: str
    config: dict[str, str | int | float | bool]
    runs: list[PlanRun]
    metrics: list[str]
    analysis: list[str]
    not_executed: str


class Readiness(StrictModel):
    schema_version: int = 1
    milestone: str = "M5.5"
    provenance: Provenance
    human_validation: dict[str, object]
    m6_verdict: str
    reproduction: ReproductionRecord
    estimand: EstimandRecord
    designs: list[DesignSummary]
    held_out: list[HeldOutSummary]
    representation: RepresentationResult
    giant: GiantComponent
    labels: LabelSummary
    labels_file: str
    labels_sha256: str
    negatives: Negatives
    phash_only: PhashOnlyPairs
    probe: ProbeResult
    probe_features_file: str
    probe_features_sha256: str
    export: ExportValidation
    blockers: list[str]
    limitations: list[str]
    verdict: Verdict
    verdict_rule: str
    answers: list[Answer]
    plan: TrainingPlan
    notes: list[str] = Field(default_factory=list)
