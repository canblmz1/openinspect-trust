"""The steps of M5.5 that need only committed files, and the rules that turn them into a verdict.

The data-dependent steps (embedding caches, released images, packages) live in
:mod:`openinspect.readiness.embeddings` and the CLI; everything here is a pure function of its
inputs, so ``openinspect readiness check`` can re-derive it in CI.
"""

from __future__ import annotations

import csv
import io
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from openinspect.files import sha256_bytes
from openinspect.readiness.design import (
    DesignParams,
    PairedDesign,
    build_design,
    composition,
    exposed_test_items,
    probe_link_kinds,
    probe_links,
)
from openinspect.readiness.heldout import linked_training_items, natural_held_out_split, purity
from openinspect.readiness.labels import Placement
from openinspect.readiness.models import (
    Answer,
    ConditionSummary,
    DesignSummary,
    EstimandRecord,
    HeldOutSummary,
    Negatives,
    PairSplitRelation,
    PhashOnlyPairs,
    PlanRun,
    TrainingPlan,
)
from openinspect.readiness.release_view import ReleaseView
from openinspect.release.checks import measure, primary_pair
from openinspect.release.manifest import EXCLUDED as EXCLUDED_FILE
from openinspect.release.manifest import split_csv
from openinspect.release.splits import EXCLUDED
from openinspect.release.verify import release_dir

DESIGN_SEEDS = (0, 1, 2)
EXPERIMENTS = Path("manifests") / "experiments"
ARTIFACTS = Path("artifacts") / "m5_5"
REPORTS = Path("reports") / "m5_5"
M6_RECORD = "artifacts/m6/evren-smoke-test.json"

CHANGES = [
    "C0 trains on the group-mates of the probe test items (the other members of their A1 "
    "constraint groups); C1 trains on replacements instead: the same number of items, of the "
    "same source and, where possible, the same boxes per class, from groups that touch no test "
    "or validation item.",
]
CONSTANT = [
    "the test set (probes and controls) and the validation set, item for item;",
    "the training-set size and the number of training items per source;",
    "the class mix of the training set (equal boxes per class wherever a mate has a replacement with the same boxes; the residual difference is reported);",
    "every other training item (the core);",
    "the release, the taxonomy, the image files, the training configuration and the seeds.",
]


def _csv(header: Sequence[str], rows: Sequence[Sequence[object]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def roles_csv(view: ReleaseView, design: PairedDesign, links: Sequence[str]) -> bytes:
    replaces = {r.replacement: r.mate for r in design.replacements if r.replacement is not None}
    rows = sorted(
        (
            item.global_id,
            item.source,
            design.roles[k],
            design.exposure_group[k] or "",
            links[k],
            replaces.get(item.global_id, ""),
        )
        for k, item in enumerate(view.items)
    )
    return _csv(["id", "source", "role", "exposure_group", "probe_link", "replaces"], rows)


def design_stage(
    view: ReleaseView, seeds: Sequence[int] = DESIGN_SEEDS
) -> tuple[list[DesignSummary], dict[str, bytes], dict[str, list[str]]]:
    """Summaries, files to write (repository path -> bytes) and the C0/C1 splits per design."""
    version = view.config.version
    folder = EXPERIMENTS / version
    summaries: list[DesignSummary] = []
    files: dict[str, bytes] = {}
    splits: dict[str, list[str]] = {}
    similar = {
        frozenset({(p.source_a, p.image_a), (p.source_b, p.image_b)})
        for p in view.pairs
        if primary_pair(p, view.primary)
    }
    for seed in seeds:
        params = DesignParams(seed=seed)
        design = build_design(view.items, view.groups, params)
        roles_path = (folder / f"C-design{seed}-roles.csv").as_posix()
        links = probe_link_kinds(view.items, design, view.components, similar)
        files[roles_path] = roles_csv(view, design, links)
        conditions: list[ConditionSummary] = []
        comps = {}
        for name, split in (("C0", design.c0), ("C1", design.c1)):
            path = (folder / f"{name}__design{seed}.csv").as_posix()
            files[path] = split_csv(view.items, split)
            splits[f"{name}-d{seed}"] = split
            comp = composition(view.items, split)
            comps[name] = comp
            conditions.append(
                ConditionSummary(
                    name=name,
                    file=path,
                    sha256=sha256_bytes(files[path]),
                    items=comp.items,
                    boxes=comp.boxes,
                    measure=measure(
                        view.items, split, view.constraints, view.pairs, view.primary, view.sha256
                    ),
                    exposed_test_items=len(exposed_test_items(split, view.groups)),
                )
            )
        roles = Counter(design.roles)
        sources = sorted({i.source for i in view.items})
        train0, train1 = comps["C0"].boxes.get("train", {}), comps["C1"].boxes.get("train", {})
        summaries.append(
            DesignSummary(
                seed=seed,
                params={k: v for k, v in asdict(params).items() if k != "seed"},
                roles={
                    r: roles[r] for r in ("probe", "control", "val", "core", "mate", "replacement")
                },
                roles_file=roles_path,
                roles_sha256=sha256_bytes(files[roles_path]),
                test_items=roles["probe"] + roles["control"],
                probe_links=probe_links(links),
                probes={
                    s: sum(
                        1
                        for i, r in zip(view.items, design.roles, strict=True)
                        if r == "probe" and i.source == s
                    )
                    for s in sources
                },
                controls={
                    s: sum(
                        1
                        for i, r in zip(view.items, design.roles, strict=True)
                        if r == "control" and i.source == s
                    )
                    for s in sources
                },
                shortfalls=design.shortfalls,
                replacements=dict(sorted(Counter(r.match for r in design.replacements).items())),
                conditions=conditions,
                train_box_difference={
                    c: train0.get(c, 0) - train1.get(c, 0)
                    for c in sorted(set(train0) | set(train1))
                },
                train_items_equal_by_source=comps["C0"].items.get("train")
                == comps["C1"].items.get("train"),
                changes=CHANGES,
                constant=CONSTANT,
            )
        )
    return summaries, files, splits


def heldout_stage(
    view: ReleaseView,
) -> tuple[list[HeldOutSummary], dict[str, bytes], dict[str, list[str]]]:
    folder = EXPERIMENTS / view.config.version
    out: list[HeldOutSummary] = []
    files: dict[str, bytes] = {}
    splits: dict[str, list[str]] = {}
    seed, val = view.config.seed, view.config.splits.held_out_val
    for source in sorted({i.source for i in view.items}):
        strict = view.schemes[f"B-{source}"]
        natural = natural_held_out_split(view.items, view.groups, source, val, seed)
        natural_path = (folder / f"B-natural-{source}__seed{seed}.csv").as_posix()
        files[natural_path] = split_csv(view.items, natural)
        splits[f"B-strict-{source}"] = strict
        splits[f"B-natural-{source}"] = natural
        strict_entry = next(e for e in view.manifest.splits if e.name == f"B-{source}")
        for regime, split, path, digest in (
            ("B-strict", strict, strict_entry.file, strict_entry.sha256),
            ("B-natural", natural, natural_path, sha256_bytes(files[natural_path])),
        ):
            p = purity(view.items, split, source)
            out.append(
                HeldOutSummary(
                    fold=source,
                    regime=regime,  # type: ignore[arg-type]
                    file=path,
                    sha256=digest,
                    items=composition(view.items, split).items,
                    measure=measure(
                        view.items, split, view.constraints, view.pairs, view.primary, view.sha256
                    ),
                    pure=p.ok,
                    test_sources=p.test_sources,
                    excluded=p.excluded,
                    linked_training_items=linked_training_items(split, view.groups),
                )
            )
    return out, files, splits


def estimand(view: ReleaseView) -> EstimandRecord:
    a0, a1 = view.schemes["A0"], view.schemes["A1"]
    sources = sorted({i.source for i in view.items})

    def test(split: Sequence[str]) -> dict[str, int]:
        c = Counter(i.source for i, s in zip(view.items, split, strict=True) if s == "test")
        return {s: c[s] for s in sources}

    t0, t1 = test(a0), test(a1)
    return EstimandRecord(
        a0_test=t0,
        a1_test=t1,
        test_overlap=sum(1 for x, y in zip(a0, a1, strict=True) if x == y == "test"),
        a0_train_holds_a1_test=sum(
            1 for x, y in zip(a0, a1, strict=True) if y == "test" and x == "train"
        ),
        a1_test_without_source=[s for s in sources if t1[s] == 0],
        reading=[
            "A0 and A1 do not share their test sets: they are different evaluation sets of different size and composition.",
            "A1 has no PCB-Defect test item, A0 has; a pooled A0 - A1 difference therefore mixes leakage with a change of what is evaluated.",
            "A0 - A1 stays a descriptive comparison of two historical split regimes. The controlled estimand is C0 - C1 on one common test set.",
        ],
    )


def negatives(root: Path, view: ReleaseView) -> Negatives:
    rows = pq.read_table(release_dir(root, view.config.version) / EXCLUDED_FILE).to_pylist()
    counts = Counter(str(r["source"]) for r in rows if r["reason"] == "no_boxes")
    sources = sorted(s.source for s in view.manifest.sources)
    return Negatives(
        available={s: counts[s] for s in sources},
        released=sum(1 for i in view.items if not i.boxes),
        excluded_reason="no_boxes (configs/release.yaml: negatives: exclude; decision T34)",
        policy="images without a box are excluded from the release, so from every split regime",
        same_in_every_regime=True,
        untested=[
            "false positives on defect-free patches: no test set contains an image without a defect, so precision on clean images is not measured;",
            "PCB-IND's hard negatives are AOI false calls (patches the inspection machine flagged that hold no defect): the deployment case of rejecting a false alarm is not tested;",
            "image-level defect/no-defect decisions: every test image holds at least one box, so a model that always predicts a defect is not penalised at image level.",
        ],
    )


def _relation(a: set[str], b: set[str]) -> str:
    if not a or not b:
        return "not_both_assigned"
    names = a | b
    if len(names) == 1:
        return "same_split"
    if {"train", "test"} <= names:
        return "train_test"
    if {"train", "val"} <= names:
        return "train_val"
    return "val_test"


def phash_only_stage(
    view: ReleaseView,
    thresholds_small: Mapping[str, float],
    base_cosine: Mapping[tuple[tuple[str, str], tuple[str, str]], float] | None,
    regimes: Mapping[str, Sequence[str]],
) -> tuple[PhashOnlyPairs, bytes]:
    """M3 candidate pairs that only the hash put in review (below the review cosine), both released."""
    table = pq.read_table(
        view.root / "artifacts" / "m3" / "duplicate-pairs.parquet",
        columns=[
            "source_a",
            "image_a",
            "source_b",
            "image_b",
            "category",
            "cosine",
            "phash_distance",
        ],
    ).to_pylist()
    released = {i.item.key for i in view.items}
    by_regime: dict[str, dict[tuple[str, str], set[str]]] = {}
    for name, split in regimes.items():
        mapping: dict[tuple[str, str], set[str]] = {}
        for item, s in zip(view.items, split, strict=True):
            if s != EXCLUDED:
                mapping.setdefault(item.item.key, set()).add(s)
        by_regime[name] = mapping
    rows: list[list[object]] = []
    distances: Counter[str] = Counter()
    small_cos: list[float] = []
    base_cos: list[float] = []
    relations: dict[str, Counter[str]] = {name: Counter() for name in regimes}
    same = cross = 0
    for r in table:
        if r["category"] != "REVIEW_REQUIRED" or float(r["cosine"]) >= thresholds_small["review"]:
            continue
        ka, kb = (str(r["source_a"]), str(r["image_a"])), (str(r["source_b"]), str(r["image_b"]))
        if ka not in released or kb not in released:
            continue
        b = None if base_cosine is None else base_cosine.get((ka, kb), base_cosine.get((kb, ka)))
        row: list[object] = [
            ka[0],
            ka[1],
            kb[0],
            kb[1],
            int(r["phash_distance"]),
            round(float(r["cosine"]), 6),
            "" if b is None else round(b, 6),
        ]
        for name in regimes:
            rel = _relation(by_regime[name].get(ka, set()), by_regime[name].get(kb, set()))
            relations[name][rel] += 1
            row.append(rel)
        rows.append(row)
        distances[str(int(r["phash_distance"]))] += 1
        small_cos.append(float(r["cosine"]))
        if b is not None:
            base_cos.append(b)
        if ka[0] == kb[0]:
            same += 1
        else:
            cross += 1
    data = _csv(
        [
            "source_a",
            "image_a",
            "source_b",
            "image_b",
            "phash_distance",
            "cosine_small",
            "cosine_base",
            *regimes,
        ],
        sorted(rows, key=lambda r: tuple(str(x) for x in r[:4])),
    )

    def stats(values: list[float]) -> dict[str, float]:
        if not values:
            return {}
        v = np.array(values)
        return {
            "min": round(float(v.min()), 6),
            "median": round(float(np.median(v)), 6),
            "max": round(float(v.max()), 6),
        }

    summary = PhashOnlyPairs(
        file=(ARTIFACTS / "phash-only-pairs.csv").as_posix(),
        sha256=sha256_bytes(data),
        pairs=len(rows),
        same_source=same,
        cross_source=cross,
        phash_distance=dict(sorted(distances.items())),
        cosine_small=stats(small_cos),
        cosine_base=stats(base_cos),
        relations=[
            PairSplitRelation(
                regime=name,
                train_test=c["train_test"],
                train_val=c["train_val"],
                val_test=c["val_test"],
                same_split=c["same_split"],
                not_both_assigned=c["not_both_assigned"],
            )
            for name, c in relations.items()
        ],
    )
    return summary, data


def placements_csv(placements: Sequence[Placement]) -> bytes:
    return _csv(
        [
            "review_id",
            "check",
            "signal",
            "source",
            "image",
            "ann_index",
            "category",
            "released_items",
            "related_items",
            "reason",
        ],
        [
            [
                p.review_id,
                p.check,
                p.signal,
                p.source,
                p.image,
                "" if p.ann_index is None else p.ann_index,
                p.category,
                ";".join(p.released_items),
                ";".join(p.related_items),
                p.reason,
            ]
            for p in placements
        ],
    )


# ------------------------------------------------------------------------------ verdict


VERDICT_RULE = (
    "NOT TRAINING READY if any blocker holds: M6 did not pass; the committed M5 splits do not "
    "reproduce from their inputs; a package fails the independent export check; a released box "
    "is FATAL; a controlled design leaves a test item exposed in C1 or none exposed in C0; a "
    "held-out split mixes sources. Otherwise TRAINING READY WITH EXPLICIT LIMITATIONS if any "
    "limitation is recorded, else TRAINING READY."
)


def blockers(
    *,
    m6_verdict: str,
    reproduced: bool,
    exports_ok: bool,
    fatal: int,
    designs: Sequence[DesignSummary],
    held_out: Sequence[HeldOutSummary],
) -> list[str]:
    found: list[str] = []
    if m6_verdict != "PASS":
        found.append(f"M6 verdict is {m6_verdict}")
    if not reproduced:
        found.append("the committed M5 splits do not reproduce from the committed inputs")
    if not exports_ok:
        found.append("a package fails the independent export validation")
    if fatal:
        found.append(f"{fatal} released boxes have invalid geometry (FATAL)")
    for d in designs:
        by = {c.name: c for c in d.conditions}
        if by["C1"].exposed_test_items != 0 or by["C1"].measure.supplied_groups_crossing != 0:
            found.append(f"design {d.seed}: C1 leaves test items exposed")
        if by["C0"].exposed_test_items == 0:
            found.append(f"design {d.seed}: C0 exposes no test item")
    for h in held_out:
        if not h.pure:
            found.append(f"{h.regime} {h.fold} mixes sources between training and test")
    return found


def verdict(blocking: Sequence[str], limitations: Sequence[str]) -> str:
    if blocking:
        return "NOT TRAINING READY"
    return "TRAINING READY WITH EXPLICIT LIMITATIONS" if limitations else "TRAINING READY"


TRAINING_CONFIG: dict[str, str | int | float | bool] = {
    "imgsz": 640,
    "epochs": 100,
    "patience": 20,
    "batch": 32,
    "optimizer": "SGD",
    "lr0": 0.01,
    "lrf": 0.01,
    "momentum": 0.937,
    "weight_decay": 0.0005,
    "warmup_epochs": 3,
    "augmentation": "Ultralytics defaults for detection (mosaic 1.0 closed for the last 10 epochs, HSV jitter, translate 0.1, scale 0.5, fliplr 0.5; no rotation, no mixup)",
    "deterministic": True,
    "val_metric_for_early_stopping": "mAP50-95 on the run's own validation split",
    "conf_for_evaluation": 0.001,
    "iou_nms": 0.7,
    "max_det": 300,
    "same_for_every_run": True,
}


def plan(
    design_seeds: Sequence[int],
    sources: Sequence[str],
    natural_differs: Sequence[str],
    version: str,
) -> TrainingPlan:
    """The M7 run matrix; nothing here is executed."""
    folder = (EXPERIMENTS / version).as_posix()
    splits = f"manifests/splits/{version}"
    runs: list[PlanRun] = []

    def package(scheme: str) -> str:
        return f"<data>/exports/{version}/openinspect-trust-{version}-{scheme}-yolo.zip"

    for training_seed in (0, 1, 2):
        for c in ("C0", "C1"):
            runs.append(
                PlanRun(
                    run_id=f"{c}-d0-s{training_seed}",
                    regime=f"{c} (design 0)",
                    split_file=f"{folder}/{c}__design0.csv",
                    package=package(f"{c}-d0"),
                    training_seed=training_seed,
                    purpose="primary paired contrast C0 - C1 on the common test set",
                )
            )
    for seed in design_seeds:
        if seed == 0:
            continue
        for c in ("C0", "C1"):
            runs.append(
                PlanRun(
                    run_id=f"{c}-d{seed}-s0",
                    regime=f"{c} (design {seed})",
                    split_file=f"{folder}/{c}__design{seed}.csv",
                    package=package(f"{c}-d{seed}"),
                    training_seed=0,
                    purpose="replication over another seeded design draw",
                )
            )
    for scheme in ("A0", "A1"):
        runs.append(
            PlanRun(
                run_id=f"{scheme}-s0",
                regime=scheme,
                split_file=f"{splits}/{scheme}__seed0.csv",
                package=package(scheme),
                training_seed=0,
                purpose="historical regime, descriptive only (different test sets)",
            )
        )
    for source in sources:
        runs.append(
            PlanRun(
                run_id=f"B-strict-{source}-s0",
                regime=f"B-strict, {source} held out",
                split_file=f"{splits}/B-{source}__seed0.csv",
                package=package(f"B-{source}"),
                training_seed=0,
                purpose="unseen source, known machine-similarity overlap removed",
            )
        )
    for source in natural_differs:
        runs.append(
            PlanRun(
                run_id=f"B-natural-{source}-s0",
                regime=f"B-natural, {source} held out",
                split_file=f"{folder}/B-natural-{source}__seed0.csv",
                package=package(f"B-natural-{source}"),
                training_seed=0,
                purpose="unseen source under naturally occurring cross-source similarity",
            )
        )
    return TrainingPlan(
        model="YOLO11n, initialised from the official COCO-pretrained yolo11n.pt",
        config=dict(TRAINING_CONFIG),
        runs=runs,
        metrics=[
            "mAP50 and mAP50-95 on the test split, from one local evaluator on the raw predictions",
            "AP50 per class (short, open, mouse_bite, spurious_copper)",
            "per source on every test set that mixes sources",
            "for C0 and C1: separately on the probes (exposed in C0) and on the controls (exposed in neither)",
        ],
        analysis=[
            "primary estimand: mAP50-95(C0) - mAP50-95(C1) on the probes of design 0, mean over the three training seeds; the controls estimate what the swap itself does and should be near zero",
            "the probes are also split by their link to the mates (`probe_link` in the roles file): visually linked (crop sibling, similar pair, same component) and metadata only (same batch or design family), because the two kinds of exposure may differ in effect",
            "probes and controls are different kinds of items (probes sit in groups, controls are mostly singletons): each is compared between C0 and C1, never with the other",
            "uncertainty: paired bootstrap over test items grouped by their A1 constraint group (1,000 resamples), on the same test set for C0 and C1; seed-to-seed spread reported next to it",
            "replication: the sign and size of C0 - C1 on designs 1 and 2 (one seed each)",
            "C0 - C1 is also reported per source, next to the DINOv2-base similar pairs that each condition keeps between train and test (representation-sensitivity.md): where C1 keeps such pairs, that part of the contrast holds only under the DINOv2-small grouping",
            "A0 and A1 are reported per source and described, not differenced as a leakage effect",
            "B-strict and B-natural are read as source shift (the source probe shows strong source signatures), not as leakage",
        ],
        not_executed="Nothing of this plan has run. M7 starts only after the maintainer approves the EVREN compute budget.",
    )


def load_json(path: Path) -> dict[str, object]:
    data: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
    return data


def answers(texts: Sequence[str]) -> list[Answer]:
    questions = [
        "Is M6 PASS?",
        "Is the full export structurally valid?",
        "How many release items are affected by M4 review findings?",
        "Can A0/A1 score differences be interpreted?",
        "Is a paired/common evaluation design available?",
        "How representation-sensitive is A1?",
        "What is happening with the PCB-Defect giant component?",
        "How predictable is source identity?",
        "What is B-natural?",
        "What is B-strict?",
        "What claims are allowed without human review?",
        "Can M7 EVREN training begin?",
    ]
    return [
        Answer(number=k + 1, question=q, answer=a)
        for k, (q, a) in enumerate(zip(questions, texts, strict=True))
    ]
