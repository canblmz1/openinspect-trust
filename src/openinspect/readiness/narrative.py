"""The limitations and the twelve answers of the readiness report, written from the numbers.

Nothing here is free text about the results: every sentence takes its numbers from the result
models, so the report cannot drift from ``readiness.json``.
"""

from __future__ import annotations

from collections.abc import Sequence

from openinspect.readiness.design import SHORTFALLS
from openinspect.readiness.giant import GiantComponent
from openinspect.readiness.labels import LabelSummary
from openinspect.readiness.models import (
    DesignSummary,
    EstimandRecord,
    ExportValidation,
    HeldOutSummary,
    Negatives,
    PhashOnlyPairs,
)
from openinspect.readiness.probe import ProbeResult
from openinspect.readiness.representation import RepresentationResult


def _pct(value: float) -> str:
    return f"{100 * value:.1f}%"


def _by_source(counts: dict[str, int]) -> str:
    return ", ".join(f"`{s}` {v:,}" for s, v in counts.items() if v) or "none"


def best_probe(probe: ProbeResult, features: str, folds: str = "stratified") -> float:
    return max(
        s.balanced_accuracy for s in probe.scores if s.features == features and s.folds == folds
    )


def limitations(
    *,
    validation_status: str,
    representation: RepresentationResult,
    giant: GiantComponent,
    designs: Sequence[DesignSummary],
    labels: LabelSummary,
    negatives: Negatives,
    phash: PhashOnlyPairs,
    probe: ProbeResult,
    held_out: Sequence[HeldOutSummary],
) -> list[str]:
    found: list[str] = []
    if validation_status != "COMPLETE":
        found.append(
            f"Human validation of the M3 similarity findings: {validation_status}. Every visual "
            "similarity component that A1, B and the C designs rely on is machine-detected "
            "potential leakage; no person has checked whether its images are duplicates."
        )
    if representation.material:
        found.append(
            "The group-aware split is representation-sensitive: an A1 built from DINOv2-base "
            "components differs materially ("
            + "; ".join(representation.material_reasons)
            + "). Results from A1, B and C hold for the DINOv2-small grouping; the base-built A1 "
            f"would leave {representation.a1_base_primary_pairs_crossing:,} small-level primary pairs "
            "across its splits."
        )
    c1 = {
        name: counts
        for name, counts in representation.designs_base_pairs_train_test.items()
        if name.startswith("C1-") and any(counts.values())
    }
    if c1:
        found.append(
            "Under DINOv2-base, C1 does not separate train and test completely: "
            + "; ".join(
                f"`{name}` keeps {sum(counts.values()):,} base similar pairs between them ({_by_source(counts)})"
                for name, counts in c1.items()
            )
            + ". The C contrast is defined by the DINOv2-small grouping, so C0 - C1 is reported per "
            "source and the part of a source with such pairs holds only under that grouping."
        )
    if giant.largest_group > 0.5 * giant.items:
        tested = [d.probes.get(giant.source, 0) + d.controls.get(giant.source, 0) for d in designs]
        found.append(
            f"`{giant.source}`: one constraint group holds {giant.largest_group:,} of its "
            f"{giant.items:,} crops (verdict {giant.verdict}). It has no A1 test item and no "
            "validation item in the C designs; the C designs test only crops outside that group "
            f"({', '.join(str(t) for t in tested)} in designs "
            f"{', '.join(str(d.seed) for d in designs)}), and the whole source is tested only "
            "when it is held out (B)."
        )
    shortfall = {
        source: values
        for d in designs[:1]
        for source, values in d.shortfalls.items()
        if any(values.values())
    }
    if shortfall:
        found.append(
            "The C designs miss their targets for "
            + ", ".join(
                f"`{s}` ({', '.join(f'{k} {v[k]}' for k in SHORTFALLS if v.get(k))})"
                for s, v in sorted(shortfall.items())
            )
            + ": too few groups small enough to be split or held out."
        )
    residual = {c: v for d in designs[:1] for c, v in d.train_box_difference.items() if v}
    if residual:
        found.append(
            "C0 and C1 training boxes per class differ slightly (design 0, C0 minus C1: "
            + ", ".join(f"{c} {v:+d}" for c, v in residual.items())
            + ") where no replacement with the same boxes per class was left."
        )
    relevant = labels.by_category.get("TRAINING_RELEVANT", 0) + labels.by_category.get(
        "LIMITATION_ONLY", 0
    )
    if relevant:
        found.append(
            "Released items with an unreviewed M4 finding: "
            f"{labels.released_items_affected['TRAINING_RELEVANT']} with a training-relevant finding "
            f"and {labels.released_items_affected['LIMITATION_ONLY']} with limitation-only findings "
            f"({relevant} findings); no label was corrected."
        )
    if sum(negatives.available.values()) and negatives.released == 0:
        found.append(
            f"Images without a defect are excluded from every regime ({sum(negatives.available.values()):,} "
            "available, all PCB-IND hard negatives): false positives on clean patches are not measured."
        )
    a1 = next((r for r in phash.relations if r.regime == "A1"), None)
    if a1 is not None and a1.train_test:
        found.append(
            f"{a1.train_test} pHash-only candidate pairs lie across A1 train and test; they are not "
            "a similarity level of the M3 protocol and stay unconstrained (P2)."
        )
    if best_probe(probe, "metadata") >= 0.95:
        found.append(
            f"Source identity is trivially predictable (balanced accuracy {_pct(best_probe(probe, 'metadata'))} "
            f"from image size and file format; {_pct(best_probe(probe, 'boxes+pixels'))} from box and colour "
            "statistics alone): B measures a large source and domain shift, not only generalization."
        )
    strict_links = [h for h in held_out if h.regime == "B-strict" and h.linked_training_items]
    if strict_links:
        found.append(
            "B-strict removes training items that share a constraint *directly* with a held-out "
            "item; "
            + ", ".join(
                f"{h.linked_training_items:,} training items of the `{h.fold}` fold remain linked transitively"
                for h in strict_links
            )
            + "."
        )
    return found


def answer_texts(
    *,
    m6_verdict: str,
    export: ExportValidation,
    labels: LabelSummary,
    estimand: EstimandRecord,
    designs: Sequence[DesignSummary],
    representation: RepresentationResult,
    giant: GiantComponent,
    probe: ProbeResult,
    held_out: Sequence[HeldOutSummary],
    validation_status: str,
    verdict: str,
    blockers: Sequence[str],
) -> list[str]:
    d0 = designs[0]
    by = {c.name: c for c in d0.conditions}
    packages = ", ".join(
        f"`{p.scheme}` {'valid' if p.internal_ok and (p.ultralytics is None or p.ultralytics.ok) else 'INVALID'}"
        for p in export.packages
    )
    overhang = max((p.internal_max_overhang_px for p in export.packages), default=0.0)
    if overhang:
        packages += (
            f" (boxes that leave their image by less than half a pixel pass, at most {overhang:.4f} "
            "px; see export-validation.md)"
        )
    if verdict == "NOT TRAINING READY":
        start = "No: " + "; ".join(blockers) + ". The M7 plan is not executed."
    else:
        start = (
            "Yes"
            + (", with the explicit limitations above" if verdict != "TRAINING READY" else "")
            + ", once the maintainer approves the EVREN compute; the M7 plan (m7-plan.md) is not "
            "executed here."
        )
    natural = [h for h in held_out if h.regime == "B-natural"]
    strict = [h for h in held_out if h.regime == "B-strict"]
    c0_pairs = representation.designs_base_pairs_train_test.get(f"C0-d{d0.seed}", {})
    c1_pairs = representation.designs_base_pairs_train_test.get(f"C1-d{d0.seed}", {})
    return [
        f"{m6_verdict}. The 20-item YOLO Detection package imported with matching counts, classes and the supplied 10/5/5 split, and a frozen version kept it (reports/m6/evren-smoke-test.md).",
        f"Packages checked: {packages}. Each was read by an in-repository parser that shares no code with the exporter and by the Ultralytics dataset checks.",
        f"{labels.findings} findings: {labels.by_category['FATAL']} FATAL, {labels.by_category['TRAINING_RELEVANT']} TRAINING_RELEVANT, {labels.by_category['LIMITATION_ONLY']} LIMITATION_ONLY, {labels.by_category['NOT_IN_RELEASE']} NOT_IN_RELEASE; released items affected: {labels.released_items_affected['TRAINING_RELEVANT']} training-relevant and {labels.released_items_affected['LIMITATION_ONLY']} limitation-only.",
        f"Not as a leakage effect. A0 tests {sum(estimand.a0_test.values()):,} items, A1 {sum(estimand.a1_test.values()):,}; they share {estimand.test_overlap} test items, A0 trains on {estimand.a0_train_holds_a1_test} of A1's test items, and A1 has no test item from {', '.join(estimand.a1_test_without_source) or 'no source missing'}. A0 - A1 stays descriptive.",
        f"Yes: C0/C1 with one common test set of {d0.test_items} items ({sum(d0.probes.values())} probes exposed in C0, {sum(d0.controls.values())} controls) and one validation set; C0 exposes {by['C0'].exposed_test_items} test items through {by['C0'].measure.supplied_groups_crossing} crossing constraint groups, C1 exposes {by['C1'].exposed_test_items} ({by['C1'].measure.supplied_groups_crossing} crossing). Three seeded designs exist.",
        f"Materially: an A1 built from DINOv2-base components moves {representation.changed_items:,} items ({_pct(representation.changed_share)}) to another split, and would leave {representation.a1_base_primary_pairs_crossing:,} small-level primary pairs across its splits; the committed A1 cuts {sum(representation.a1_cuts_base.values())} base constraint groups. In design {d0.seed}, {sum(c1_pairs.values()):,} DINOv2-base similar pairs lie between C1's train and test sets ({_by_source(c1_pairs)}; {sum(c0_pairs.values()):,} in C0).",
        f"Verdict {giant.verdict}: " + "; ".join(giant.causes or ["no cause rule fired"]) + ".",
        f"Very predictable: {_pct(best_probe(probe, 'metadata'))} balanced accuracy from size and format, {_pct(best_probe(probe, 'boxes+pixels'))} from boxes and colour statistics (majority baseline {_pct(probe.majority_baseline)}).",
        "The held-out source is the whole test set; every other item is available for training and validation (group-aware), and naturally similar cross-source items are kept: "
        + ", ".join(
            f"`{h.fold}` keeps {h.linked_training_items} linked training items" for h in natural
        )
        + ".",
        "The M5 split B: the held-out source is the test set and training items that share a constraint directly with a held-out item are excluded: "
        + ", ".join(f"`{h.fold}` excludes {h.excluded}" for h in strict)
        + ".",
        f"Human validation is {validation_status}. Allowed: machine-detected potential leakage, visual similarity group, embedding-defined component, and measured differences between regimes defined by them. Not allowed: confirmed duplicate, confirmed leakage, same physical board, human-validated leakage.",
        f"{verdict}. {start}",
    ]
