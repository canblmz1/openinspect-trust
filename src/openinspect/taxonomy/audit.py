"""The M4 audit: every number of the M4 reports, built from the mapped records (``audit.json``).

The reports are a pure function of this audit and of ``configs/taxonomy.yaml``, so the committed
reports can be checked against the committed audit without any data.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Literal

import numpy as np
from pydantic import Field

from openinspect.provenance.schema import StrictModel
from openinspect.taxonomy.config import QualityRules, Status, Taxonomy
from openinspect.taxonomy.mapping import MappedImage
from openinspect.taxonomy.quality import SIGNALS, Finding, NeighbourAgreement
from openinspect.validation import HumanValidation

EXAMPLES_PER_SIGNAL = 5


class LabelRow(StrictModel):
    """One original label of one source and what the mapping makes of it."""

    source: str
    original_label: str
    declared: bool  # listed by the source manifest
    boxes: int
    images: int
    normalized_label: str | None
    status: Status
    family: str | None
    benchmark: bool


class SourceRow(StrictModel):
    """What the mapping leaves of one source for a cross-source release."""

    source: str
    acquisition_id: str | None
    images: int
    boxes: int
    negatives: int  # images without any box
    eligible_images: int  # every box maps onto a benchmark class
    excluded_images: int  # at least one box of another class (SPEC 7.4: the whole image)
    eligible_boxes: int
    excluded_boxes: int  # all boxes of the excluded images
    benchmark_boxes_in_excluded: int  # benchmark-class boxes lost with their excluded image
    excluded_by: dict[str, int]  # original label -> excluded images that contain it
    eligible_by_split: dict[str, int]  # original split ("none" without one) -> eligible images


class Reach(StrictModel):
    source: str
    original_label: str
    status: Status


class ClassRow(StrictModel):
    """One normalized class: which source labels reach it, and with what status."""

    normalized_label: str
    family: str
    benchmark: bool
    reached_by: list[Reach]
    candidate_of: list[Reach]  # AMBIGUOUS labels that name this class as their candidate


class Spread(StrictModel):
    n: int
    p10: float
    median: float
    p90: float


class ClassGeometry(StrictModel):
    """The size of one benchmark class's boxes in one source (eligible images only)."""

    normalized_label: str
    source: str
    boxes: int
    images: int
    relative_area: Spread | None  # box area / image area
    long_side_px: Spread | None
    image_long_side_px: Spread | None


class SignalCount(StrictModel):
    signal: str
    check: str
    source: str
    findings: int
    images: int
    boxes: int


class Example(StrictModel):
    signal: str
    source_id: str
    image_id: str
    ann_index: int | None
    original_label: str
    related_image_id: str
    measure: float | None
    detail: str


class Agreement(StrictModel):
    scope: str
    near_pairs: int
    near_pairs_differing: int
    strict_pairs: int
    strict_pairs_differing: int


class M4Run(StrictModel):
    code_commit: str | None
    code_dirty: bool | None
    taxonomy_sha256: str
    phash_max: int  # the M3 pHash candidate distance used by the near-duplicate check
    near_threshold: float  # the M3 near-level cosine


class M4Audit(StrictModel):
    schema_version: Literal[1] = 1
    run: M4Run
    inputs: dict[str, str]  # input file (data-directory or repository path) -> SHA-256
    benchmark_classes: list[str]
    labels: list[LabelRow]
    sources: list[SourceRow]
    classes: list[ClassRow]
    geometry: list[ClassGeometry]
    rules: QualityRules
    signals: list[SignalCount]
    examples: list[Example]
    agreement: list[Agreement]
    review_rows: int
    human_validation: HumanValidation
    artifacts: dict[str, str] = Field(default_factory=dict)  # file name -> SHA-256


def spread(values: Sequence[float]) -> Spread | None:
    if not values:
        return None
    v = np.asarray(values, dtype=np.float64)
    p10, median, p90 = np.quantile(v, [0.1, 0.5, 0.9])
    return Spread(n=len(v), p10=float(p10), median=float(median), p90=float(p90))


def label_rows(
    images: Sequence[MappedImage], taxonomy: Taxonomy, declared: Mapping[str, Sequence[str]]
) -> list[LabelRow]:
    boxes: Counter[tuple[str, str]] = Counter()
    holders: dict[tuple[str, str], set[str]] = defaultdict(set)
    for image in images:
        for m in image.boxes:
            key = (image.item.source, m.box.original_label)
            boxes[key] += 1
            holders[key].add(image.item.item_id)
    benchmark = set(taxonomy.benchmark_classes)
    rows: list[LabelRow] = []
    for source, labels in sorted(taxonomy.mappings.items()):
        for label, mapping in labels.items():
            target = mapping.normalized_label
            rows.append(
                LabelRow(
                    source=source,
                    original_label=label,
                    declared=label in declared.get(source, ()),
                    boxes=boxes[(source, label)],
                    images=len(holders[(source, label)]),
                    normalized_label=target,
                    status=mapping.status,
                    family=None if target is None else taxonomy.classes[target].family,
                    benchmark=mapping.status in ("EXACT", "COMPATIBLE") and target in benchmark,
                )
            )
    return rows


def source_rows(images: Sequence[MappedImage]) -> list[SourceRow]:
    by_source: dict[str, list[MappedImage]] = defaultdict(list)
    for image in images:
        by_source[image.item.source].append(image)
    rows: list[SourceRow] = []
    for source, members in sorted(by_source.items()):
        eligible = [i for i in members if i.eligibility == "eligible"]
        excluded = [i for i in members if i.eligibility == "excluded"]
        excluded_by: Counter[str] = Counter(label for i in excluded for label in i.excluded_by)
        rows.append(
            SourceRow(
                source=source,
                acquisition_id=members[0].item.acquisition_id,
                images=len(members),
                boxes=sum(len(i.boxes) for i in members),
                negatives=sum(1 for i in members if i.eligibility == "negative"),
                eligible_images=len(eligible),
                excluded_images=len(excluded),
                eligible_boxes=sum(len(i.boxes) for i in eligible),
                excluded_boxes=sum(len(i.boxes) for i in excluded),
                benchmark_boxes_in_excluded=sum(
                    1 for i in excluded for m in i.boxes if m.benchmark
                ),
                excluded_by=dict(sorted(excluded_by.items())),
                eligible_by_split=dict(
                    sorted(Counter(i.item.split or "none" for i in eligible).items())
                ),
            )
        )
    return rows


def class_rows(taxonomy: Taxonomy) -> list[ClassRow]:
    benchmark = set(taxonomy.benchmark_classes)
    rows: list[ClassRow] = []
    for name, definition in taxonomy.classes.items():
        reached = [
            Reach(source=source, original_label=label, status=m.status)
            for source, labels in sorted(taxonomy.mappings.items())
            for label, m in labels.items()
            if m.normalized_label == name
        ]
        candidates = [
            Reach(source=source, original_label=label, status=m.status)
            for source, labels in sorted(taxonomy.mappings.items())
            for label, m in labels.items()
            if m.candidate == name
        ]
        rows.append(
            ClassRow(
                normalized_label=name,
                family=definition.family,
                benchmark=name in benchmark,
                reached_by=reached,
                candidate_of=candidates,
            )
        )
    return rows


def geometry_rows(images: Sequence[MappedImage], benchmark: Sequence[str]) -> list[ClassGeometry]:
    area: dict[tuple[str, str], list[float]] = defaultdict(list)
    side: dict[tuple[str, str], list[float]] = defaultdict(list)
    image_side: dict[tuple[str, str], list[float]] = defaultdict(list)
    holders: dict[tuple[str, str], set[str]] = defaultdict(set)
    for image in images:
        if image.eligibility != "eligible" or not image.item.width or not image.item.height:
            continue
        pixels = image.item.width * image.item.height
        for m in image.boxes:
            key = (m.normalized_label or "", image.item.source)
            if image.item.item_id not in holders[key]:
                image_side[key].append(float(max(image.item.width, image.item.height)))
            holders[key].add(image.item.item_id)
            area[key].append(max(m.box.width, 0.0) * max(m.box.height, 0.0) / pixels)
            side[key].append(max(m.box.width, m.box.height))
    sources = sorted({image.item.source for image in images})
    return [
        ClassGeometry(
            normalized_label=name,
            source=source,
            boxes=len(area[(name, source)]),
            images=len(holders[(name, source)]),
            relative_area=spread(area[(name, source)]),
            long_side_px=spread(side[(name, source)]),
            image_long_side_px=spread(image_side[(name, source)]),
        )
        for name in benchmark
        for source in sources
    ]


def signal_counts(findings: Sequence[Finding]) -> list[SignalCount]:
    groups: dict[tuple[str, str], list[Finding]] = defaultdict(list)
    for f in findings:
        groups[(f.signal, f.source_id)].append(f)
    order = list(SIGNALS)
    return [
        SignalCount(
            signal=signal,
            check=SIGNALS[signal][0],
            source=source,
            findings=len(members),
            images=len({f.image_id for f in members if f.image_id}),
            boxes=len({(f.image_id, f.ann_index) for f in members if f.ann_index is not None}),
        )
        for (signal, source), members in sorted(
            groups.items(), key=lambda kv: (order.index(kv[0][0]), kv[0][1])
        )
    ]


def examples(findings: Sequence[Finding], per_signal: int = EXAMPLES_PER_SIGNAL) -> list[Example]:
    """The first findings of each signal in the queue order (the queue is sorted, so this is fixed)."""
    taken: Counter[str] = Counter()
    rows: list[Example] = []
    for f in findings:
        if taken[f.signal] >= per_signal:
            continue
        taken[f.signal] += 1
        rows.append(
            Example(
                signal=f.signal,
                source_id=f.source_id,
                image_id=f.image_id,
                ann_index=f.ann_index,
                original_label=f.original_label,
                related_image_id=f.related_image_id,
                measure=f.measure,
                detail=f.detail,
            )
        )
    return rows


def build_audit(
    images: Sequence[MappedImage],
    taxonomy: Taxonomy,
    declared: Mapping[str, Sequence[str]],
    findings: Sequence[Finding],
    agreement: Sequence[NeighbourAgreement],
    *,
    run: M4Run,
    inputs: Mapping[str, str],
    validation: HumanValidation,
) -> M4Audit:
    benchmark = taxonomy.benchmark_classes
    return M4Audit(
        run=run,
        inputs=dict(sorted(inputs.items())),
        benchmark_classes=benchmark,
        labels=label_rows(images, taxonomy, declared),
        sources=source_rows(images),
        classes=class_rows(taxonomy),
        geometry=geometry_rows(images, benchmark),
        rules=taxonomy.label_quality,
        signals=signal_counts(findings),
        examples=examples(findings),
        agreement=[
            Agreement(
                scope=a.scope,
                near_pairs=a.near_pairs,
                near_pairs_differing=a.near_pairs_differing,
                strict_pairs=a.strict_pairs,
                strict_pairs_differing=a.strict_pairs_differing,
            )
            for a in agreement
        ],
        review_rows=len(findings),
        human_validation=validation,
    )
