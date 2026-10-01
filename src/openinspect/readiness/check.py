"""``openinspect readiness check``: the committed M5.5 outputs against the committed inputs (CI).

No data directory is needed. Re-derived from committed files: the controlled designs, the
B-natural folds, the label-finding intersection, the source probe (from its committed feature
table), the base-built A1 (from the committed base components), the base pairs across the C
designs, the A0/A1 estimand record, the negative policy, and from the committed numbers the
blockers, the limitations, the verdict, the twelve answers and the M7 plan. Checked: the purity of
every held-out split, the identity of the common test and validation sets, that no input of an
earlier milestone changed, that every output still has its recorded SHA-256, and that the reports
are what ``readiness.json`` renders.
"""

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq

from openinspect.files import sha256_file
from openinspect.readiness.heldout import purity
from openinspect.readiness.labels import QUEUE, LabelSummary, place, read_findings, summarize
from openinspect.readiness.models import DesignSummary, HeldOutSummary, Readiness
from openinspect.readiness.narrative import answer_texts, limitations
from openinspect.readiness.pipeline import (
    M6_RECORD,
    answers,
    blockers,
    design_stage,
    estimand,
    heldout_stage,
    load_json,
    negatives,
    plan,
    verdict,
)
from openinspect.readiness.probe import FEATURES, ProbeResult, run_probe
from openinspect.readiness.release_view import ReleaseView, load_view, reproduce
from openinspect.readiness.report import render_all
from openinspect.readiness.representation import constraints_with, pairs_train_test
from openinspect.release.splits import EXCLUDED, group_split
from openinspect.validation import read_validation


def check_committed(root: Path, readiness: Readiness) -> list[str]:
    problems: list[str] = []
    for path, digest in readiness.provenance.inputs.items():
        if not (root / path).is_file() or sha256_file(root / path) != digest:
            problems.append(f"input {path} changed since M5.5 ran")
    for path, digest in readiness.provenance.outputs.items():
        if not (root / path).is_file() or sha256_file(root / path) != digest:
            problems.append(f"output {path} does not match its recorded SHA-256")
    if problems:
        return problems
    view = load_view(root)
    reproduced = reproduce(view).ok
    if not reproduced:
        problems.append("the committed M5 splits do not reproduce")
    designs, design_files, design_splits = design_stage(view, readiness.provenance.design_seeds)
    held, held_files, held_splits = heldout_stage(view)
    for path, blob in {**design_files, **held_files}.items():
        if not (root / path).is_file() or (root / path).read_bytes() != blob:
            problems.append(f"{path} does not re-derive")
    if designs != readiness.designs:
        problems.append("the design summaries do not re-derive")
    if held != readiness.held_out:
        problems.append("the held-out summaries do not re-derive")
    for name, split in held_splits.items():
        source = name.removeprefix("B-strict-").removeprefix("B-natural-")
        if not purity(view.items, split, source).ok:
            problems.append(f"{name}: the held-out source is not exactly the test set")
    for seed in readiness.provenance.design_seeds:
        c0, c1 = design_splits[f"C0-d{seed}"], design_splits[f"C1-d{seed}"]
        for name in ("test", "val"):
            if [s == name for s in c0] != [s == name for s in c1]:
                problems.append(f"design {seed}: C0 and C1 do not share the {name} set")
        train0 = sorted(i.source for i, s in zip(view.items, c0, strict=True) if s == "train")
        train1 = sorted(i.source for i, s in zip(view.items, c1, strict=True) if s == "train")
        if train0 != train1:
            problems.append(f"design {seed}: C0 and C1 differ in training items per source")
    ids = [i.global_id for i in view.items]
    regimes = {
        "A0": view.schemes["A0"],
        "A1": view.schemes["A1"],
        **{k: v for k, v in design_splits.items() if k.endswith("-d0")},
        **held_splits,
    }
    placements = place(read_findings(root / QUEUE), view.items)
    labels = summarize(
        placements, {name: dict(zip(ids, split, strict=True)) for name, split in regimes.items()}
    )
    if labels != readiness.labels:
        problems.append("the label-finding intersection does not re-derive")
    features = pq.read_table(root / readiness.probe_features_file).to_pydict()
    if sha256_file(root / readiness.probe_features_file) != readiness.probe_features_sha256:
        problems.append("the probe feature table changed")
    probe = run_probe(
        {name: features[name] for name in FEATURES},
        features["source"],
        features["global_id"],
        features["constraint_group"],
        seed=readiness.provenance.probe_seed,
    )
    if not probe_agrees(probe, readiness.probe):
        problems.append("the source probe does not re-derive from its feature table")
    membership = pq.read_table(
        root / "artifacts" / "m5_5" / "representation-membership.parquet"
    ).to_pydict()
    if membership["global_id"] != ids:
        problems.append("the representation table does not list the released items in order")
    else:
        base_components = {
            item.item.key: comp
            for item, comp in zip(view.items, membership["base_component"], strict=True)
            if comp is not None
        }
        _, keys = constraints_with(view, base_components)
        a1_base = [
            s or EXCLUDED
            for s in group_split(view.items, keys, view.config.splits.ratios, view.config.seed)
        ]
        if keys != membership["base_constraint_group"] or a1_base != membership["split_A1_base"]:
            problems.append("the base-built A1 does not re-derive from the base components")
        changed = sum(1 for x, y in zip(view.schemes["A1"], a1_base, strict=True) if x != y)
        if changed != readiness.representation.changed_items:
            problems.append("the number of items that change split under the base grouping differs")
        small = [view.components.get(i.item.key) for i in view.items]
        if small != membership["small_component"]:
            problems.append("the small components of the release items differ from M3")
    rows = (root / BASE_PAIRS).read_text(encoding="utf-8").splitlines()[1:]
    base_pairs = [(a, b, c, d) for a, b, c, d, _ in (row.split(",") for row in rows)]
    found = {
        name: pairs_train_test(view, split, base_pairs)
        for name, split in sorted(design_splits.items())
    }
    if found != readiness.representation.designs_base_pairs_train_test:
        problems.append("the base similar pairs between train and test of the C designs differ")
    problems += _decision_problems(root, readiness, view, reproduced, labels, designs, held)
    slugs = sorted(s.source for s in view.manifest.sources)
    differs = [s for s in slugs if held_splits[f"B-natural-{s}"] != held_splits[f"B-strict-{s}"]]
    if (
        plan(readiness.provenance.design_seeds, slugs, differs, view.config.version)
        != readiness.plan
    ):
        problems.append("the M7 plan does not re-derive")
    for path, text in render_all(readiness).items():
        target = root / path
        if not target.is_file() or target.read_text(encoding="utf-8") != text:
            problems.append(f"{path} is not what readiness.json renders")
    return problems


def _decision_problems(
    root: Path,
    readiness: Readiness,
    view: ReleaseView,
    reproduced: bool,
    labels: LabelSummary,
    designs: list[DesignSummary],
    held: list[HeldOutSummary],
) -> list[str]:
    """The estimand, the negatives, the blockers, the limitations, the verdict and the answers."""
    problems: list[str] = []
    est = estimand(view)
    if est != readiness.estimand:
        problems.append("the A0/A1 estimand record does not re-derive")
    negative = negatives(root, view)
    if negative != readiness.negatives:
        problems.append("the record of images without a box does not re-derive")
    m6_verdict = str(load_json(root / M6_RECORD)["verdict"])
    blocking = blockers(
        m6_verdict=m6_verdict,
        reproduced=reproduced,
        exports_ok=all(
            p.internal_ok and (p.ultralytics is None or p.ultralytics.ok)
            for p in readiness.export.packages
        ),
        fatal=labels.by_category["FATAL"],
        designs=designs,
        held_out=held,
    )
    status = read_validation(root).status
    limits = limitations(
        validation_status=status,
        representation=readiness.representation,
        giant=readiness.giant,
        designs=designs,
        labels=labels,
        negatives=negative,
        phash=readiness.phash_only,
        probe=readiness.probe,
        held_out=held,
    )
    decided = verdict(blocking, limits)
    if (blocking, limits, decided) != (
        readiness.blockers,
        readiness.limitations,
        readiness.verdict,
    ):
        problems.append("the blockers, limitations or verdict do not follow from the numbers")
    texts = answer_texts(
        m6_verdict=m6_verdict,
        export=readiness.export,
        labels=labels,
        estimand=est,
        designs=designs,
        representation=readiness.representation,
        giant=readiness.giant,
        probe=readiness.probe,
        held_out=held,
        validation_status=status,
        verdict=decided,
        blockers=blocking,
    )
    if answers(texts) != readiness.answers:
        problems.append("the twelve answers do not follow from the numbers")
    return problems


BASE_PAIRS = "artifacts/m5_5/base-similar-pairs.csv"
PROBE_TOLERANCE = 0.005  # gradient descent may differ in the last bits between BLAS builds


def probe_agrees(a: ProbeResult, b: ProbeResult, tolerance: float = PROBE_TOLERANCE) -> bool:
    """The same scores up to ``tolerance`` and the same trees (the trees are exact)."""
    if (a.items, a.sources, a.majority_baseline, a.trees, a.features) != (
        b.items,
        b.sources,
        b.majority_baseline,
        b.trees,
        b.features,
    ):
        return False
    if [(s.features, s.model, s.folds) for s in a.scores] != [
        (s.features, s.model, s.folds) for s in b.scores
    ]:
        return False
    return all(
        abs(x.accuracy - y.accuracy) <= tolerance
        and abs(x.balanced_accuracy - y.balanced_accuracy) <= tolerance
        for x, y in zip(a.scores, b.scores, strict=True)
    )
