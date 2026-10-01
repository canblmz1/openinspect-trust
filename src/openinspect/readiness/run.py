"""``openinspect readiness compute``: every M5.5 step, end to end (needs the data directory).

Inputs are the committed release, the committed M3 and M4 artifacts, the M6 record, the M3
embedding caches and the released images. Outputs are repository files (returned as bytes, the
CLI writes them) and packages under ``<data>/exports/``. Nothing of an earlier milestone is
changed.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pyarrow as pa
from numpy.typing import NDArray

from openinspect.dedup.config import DedupConfig, load_config
from openinspect.dedup.embedder import Embedder, EmbedderSpec, load_dinov2, spec_from_config
from openinspect.dedup.inventory import ImageItem, load_items
from openinspect.dedup.thresholds import Thresholds
from openinspect.exportcheck import validate_archive
from openinspect.files import parquet_bytes, replace_bytes, sha256_bytes, sha256_file
from openinspect.readiness.embeddings import ModelGroups, crop_features, model_groups, similar_pairs
from openinspect.readiness.giant import (
    RULES,
    GiantComponent,
    crop_graph,
    decompose,
    scan_graph,
    sweep,
)
from openinspect.readiness.giant import (
    verdict as giant_verdict,
)
from openinspect.readiness.labels import QUEUE, place, read_findings, summarize
from openinspect.readiness.models import (
    ExportValidation,
    ModelPin,
    PackageCheck,
    Provenance,
    Readiness,
    ReproductionRecord,
    UltralyticsCheck,
)
from openinspect.readiness.narrative import answer_texts, limitations
from openinspect.readiness.pipeline import (
    ARTIFACTS,
    DESIGN_SEEDS,
    M6_RECORD,
    VERDICT_RULE,
    answers,
    blockers,
    design_stage,
    estimand,
    heldout_stage,
    load_json,
    negatives,
    phash_only_stage,
    placements_csv,
    plan,
    verdict,
)
from openinspect.readiness.probe import FEATURES, box_features, pixel_features, run_probe
from openinspect.readiness.release_view import ReleaseView, load_view, reproduce
from openinspect.readiness.representation import analyse
from openinspect.release.export import package_members, read_items, zip_bytes
from openinspect.release.manifest import ANNOTATIONS, ITEMS, RELEASE
from openinspect.release.splits import EXCLUDED
from openinspect.release.verify import release_dir
from openinspect.validation import read_validation

Log = Callable[[str], None]
ULTRALYTICS_SCRIPT = Path("scripts") / "validate_export_ultralytics.py"
SWEEP = [round(0.90 + 0.005 * k, 3) for k in range(20)]


class RunError(Exception):
    """A step of M5.5 cannot run."""


@dataclass(frozen=True)
class Outputs:
    files: dict[str, bytes]  # repository path -> bytes
    readiness: Readiness


def _pin(config: DedupConfig, name: str) -> ModelPin:
    key, entry = config.model(name)
    return ModelPin(
        name=key,
        model_id=entry.model_id,
        revision=entry.revision,
        weights_sha256=entry.weights_sha256,
    )


def _scan_vectors(
    groups: ModelGroups, source: str
) -> tuple[list[tuple[str, str]], NDArray[np.float32], list[str | None]]:
    keep = [k for k, item in enumerate(groups.features.items) if item.source == source]
    keys = [groups.features.items[k].key for k in keep]
    families = [groups.features.items[k].group_id for k in keep]
    return keys, groups.features.vectors[keep], families


def giant_stage(
    view: ReleaseView,
    data: Path,
    small: ModelGroups,
    base: ModelGroups,
    make: Callable[[EmbedderSpec], Callable[[], Embedder] | None],
    *,
    source: str = "pcb-defect",
) -> GiantComponent:
    idx = [i for i, item in enumerate(view.items) if item.source == source]
    largest = max(sum(1 for i in idx if view.groups[i] == view.groups[j]) for j in idx)
    _, small_vectors, families = _scan_vectors(small, source)
    _, base_vectors, _ = _scan_vectors(base, source)
    level_small = small.primary.get(source, "family")
    level_base = base.primary.get(source, "family")
    t_small = getattr(small.thresholds, level_small)
    t_base = getattr(base.thresholds, level_base)
    graphs = [
        scan_graph(small_vectors, families, t_small, small.spec.name),
        scan_graph(base_vectors, families, t_base, base.spec.name),
    ]
    points = sweep(small_vectors, SWEEP, small.spec.name) + sweep(
        base_vectors, SWEEP, base.spec.name
    )
    crops_items = [view.items[i] for i in idx]
    images = data / view.manifest.images_dir
    crop_inputs = [
        ImageItem(
            source=it.source,
            item_id=it.global_id,
            path=images / it.file_name,
            sha256=view.sha256[i],
            split=None,
            group_id=it.item.group_id,
            subgroup_id=None,
            n_annotations=len(it.boxes),
            dhash=None,
            width=it.width,
            height=it.height,
        )
        for i, it in zip(idx, crops_items, strict=True)
    ]
    crop_graphs = []
    for groups, threshold in ((small, t_small), (base, t_base)):
        features = crop_features(
            crop_inputs,
            data,
            groups.spec,
            make(groups.spec),
            hashes_path=data / "m5_5" / "hashes.jsonl",
        )
        if len(features.items) != len(crop_inputs):
            raise RunError(f"{len(crop_inputs) - len(features.items)} crops have no embedding")
        crop_graphs.append(
            crop_graph(
                crops_items,
                features.vectors,
                threshold,
                groups.spec.name,
                [view.sha256[i] for i in idx],
            )
        )
    code, causes = giant_verdict(graphs[0], graphs[1], crop_graphs[0], largest)
    return GiantComponent(
        source=source,
        items=len(idx),
        largest_group=largest,
        decomposition=decompose(view.items, view.constraints, source),
        scan_graphs=graphs,
        sweep=points,
        crop_graphs=crop_graphs,
        verdict=code,
        causes=causes,
        rules=RULES,
    )


def probe_table(view: ReleaseView, images: Path) -> pa.Table:
    rows = [
        {**box_features(item), **pixel_features(images / item.file_name)} for item in view.items
    ]
    columns: dict[str, pa.Array] = {
        "global_id": pa.array([i.global_id for i in view.items], type=pa.string()),
        "source": pa.array([i.source for i in view.items], type=pa.string()),
        "constraint_group": pa.array(view.groups, type=pa.string()),
    }
    for name in FEATURES:
        columns[name] = pa.array([round(r[name], 9) for r in rows], type=pa.float64())
    return pa.table(columns)


def export_stage(
    view: ReleaseView,
    data: Path,
    regimes: Mapping[str, list[str]],
    *,
    ultralytics_python: Path | None,
    root: Path,
    log: Log,
) -> ExportValidation:
    items = read_items(release_dir(root, view.config.version), ITEMS, ANNOTATIONS)
    by_id = {item.global_id: k for k, item in enumerate(view.items)}
    names = view.manifest.taxonomy.benchmark_classes
    folder = data / "exports" / view.config.version
    checks: list[PackageCheck] = []
    for scheme, split in regimes.items():
        enriched = [
            replace(item, splits={**item.splits, scheme: split[by_id[item.global_id]]})
            for item in items
        ]
        title = f"OpenInspect-Trust {view.config.version}, split {scheme}, full package (YOLO detection)"
        members = package_members(enriched, scheme, data / view.manifest.images_dir, names, title)
        archive = zip_bytes(members)
        path = folder / f"openinspect-trust-{view.config.version}-{scheme}-yolo.zip"
        replace_bytes(path, archive)
        log(f"{scheme}: {path.name} ({len(archive) / 1e6:.0f} MB)")
        check = validate_archive(archive)
        expected: dict[str, int] = {}
        for item in enriched:
            if item.splits[scheme] != EXCLUDED:
                for b in item.boxes:
                    expected[names[b.class_id]] = expected.get(names[b.class_id], 0) + 1
        ultra = None
        if ultralytics_python is not None:
            out = data / "m5_5" / f"ultralytics-{scheme}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.unlink(missing_ok=True)  # never read a result of an earlier run
            done = subprocess.run(  # noqa: S603 - the interpreter path is given by the operator
                [str(ultralytics_python), str(root / ULTRALYTICS_SCRIPT), str(path), str(out)],
                check=False,
                capture_output=True,
            )
            if not out.is_file():
                tail = done.stderr.decode("utf-8", errors="replace")[-500:]
                raise RunError(f"the Ultralytics check of {path.name} wrote no result: {tail}")
            raw = json.loads(out.read_text(encoding="utf-8"))
            if raw["sha256"] != sha256_bytes(archive):
                raise RunError(f"Ultralytics checked another file than {path.name}")
            ultra = UltralyticsCheck(
                version=str(raw["version"]),
                ok=bool(raw["ok"]),
                totals={k: int(v) for k, v in raw["totals"].items()},
                boxes_per_class={k: int(v) for k, v in raw["boxes_per_class"].items()},
                messages_total=int(raw["messages_total"]),
                messages=list(raw["messages"]),
            )
        checks.append(
            PackageCheck(
                scheme=scheme,
                package=path.name,
                sha256=check.archive_sha256,
                bytes=len(archive),
                items=check.images,
                boxes=check.boxes,
                expected_boxes={n: expected.get(n, 0) for n in names},
                internal_ok=check.ok and check.boxes == {n: expected.get(n, 0) for n in names},
                internal_rows=check.rows,
                internal_problems=dict(check.problems),
                internal_examples=check.examples,
                internal_overhangs=check.overhangs,
                internal_max_overhang_px=round(check.max_overhang_px, 4),
                ultralytics=ultra,
            )
        )
    return ExportValidation(
        packages=checks,
        independence=[
            "Ultralytics dataset checks (ultralytics.data.utils.verify_image_label and check_det_dataset), run in a separate environment: an external implementation of the loader that trains YOLO11, sharing nothing with this repository.",
            "openinspect.exportcheck: an in-repository parser that imports nothing from openinspect (a test enforces it) and rebuilds every box from the archive alone.",
            "EVREN itself, for the 20-item smoke package only (M6): a platform import, not a check of the full packages.",
        ],
    )


def compute(
    root: Path,
    data: Path,
    *,
    ultralytics_python: Path | None,
    threads: int | None,
    log: Log,
    code: tuple[str | None, bool | None],
    packages: Sequence[str] | None = None,
) -> Outputs:
    view = load_view(root)
    reproduction = reproduce(view)
    if not reproduction.ok:
        raise RunError("the committed M5 splits do not reproduce from the committed inputs")
    config = load_config(root)
    audit = load_json(root / "artifacts" / "m3" / "audit.json")
    small_t = Thresholds.model_validate(audit["thresholds"])
    base_t = Thresholds.model_validate(audit["robustness"]["other_thresholds"])  # type: ignore[index]
    files: dict[str, bytes] = {}
    log("designs and held-out regimes")
    designs, design_files, design_splits = design_stage(view, DESIGN_SEEDS)
    held, held_files, held_splits = heldout_stage(view)
    files.update(design_files)
    files.update(held_files)
    log("representations: DINOv2-small and DINOv2-base components from the caches")
    slugs = sorted(s.source for s in view.manifest.sources)
    acquisition = {s: e.acquisition_id for s, e in config.sources.items()}
    images, _ = load_items(data, slugs, acquisition=acquisition)
    small = model_groups(images, data, spec_from_config(config, "dinov2-small"), small_t)
    base = model_groups(images, data, spec_from_config(config, "dinov2-base"), base_t)
    released = {item.item.key for item in view.items}
    base_pairs = similar_pairs(base, released)
    representation, base_keys, a1_base = analyse(
        view,
        base.components,
        base_primary=base.primary,
        small_model=small.spec.model_key,
        base_model=base.spec.model_key,
        small_thresholds={"family": small_t.family, "near": small_t.near},
        base_thresholds={"family": base_t.family, "near": base_t.near},
        base_pairs=[p[:4] for p in base_pairs],
        designs=design_splits,
    )
    small_by_item = [view.components.get(i.item.key) for i in view.items]
    base_by_item = [base.components.get(i.item.key) for i in view.items]
    files[(ARTIFACTS / "representation-membership.parquet").as_posix()] = parquet_bytes(
        pa.table(
            {
                "global_id": pa.array([i.global_id for i in view.items], type=pa.string()),
                "source": pa.array([i.source for i in view.items], type=pa.string()),
                "small_component": pa.array(small_by_item, type=pa.string()),
                "base_component": pa.array(base_by_item, type=pa.string()),
                "small_constraint_group": pa.array(view.groups, type=pa.string()),
                "base_constraint_group": pa.array(base_keys, type=pa.string()),
                "split_A1": pa.array(view.schemes["A1"], type=pa.string()),
                "split_A1_base": pa.array(a1_base, type=pa.string()),
            }
        )
    )
    files[(ARTIFACTS / "base-similar-pairs.csv").as_posix()] = (
        "source_a,image_a,source_b,image_b,cosine\n"
        + "".join(f"{a},{b},{c},{d},{s}\n" for a, b, c, d, s in base_pairs)
    ).encode("utf-8")

    def make(spec: EmbedderSpec) -> Callable[[], Embedder] | None:
        _, entry = config.model(spec.name)
        return lambda: load_dinov2(spec, entry, data_dir=data, threads=threads)  # pragma: no cover

    log("PCB-Defect: scan and crop graphs (crops may need the model once)")
    giant = giant_stage(view, data, small, base, make)
    log("label findings in the release")
    findings = read_findings(root / QUEUE)
    placements = place(findings, view.items)
    ids = [i.global_id for i in view.items]
    regimes: dict[str, list[str]] = {
        "A0": view.schemes["A0"],
        "A1": view.schemes["A1"],
        **{k: v for k, v in design_splits.items() if k.endswith("-d0")},
        **held_splits,
    }
    labels = summarize(
        placements, {name: dict(zip(ids, split, strict=True)) for name, split in regimes.items()}
    )
    files[(ARTIFACTS / "release-label-findings.csv").as_posix()] = placements_csv(placements)
    base_vectors = {
        item.key: base.features.vectors[k] for k, item in enumerate(base.features.items)
    }
    pair_cos: dict[tuple[tuple[str, str], tuple[str, str]], float] = {}
    phash_summary, phash_data = phash_only_stage(view, small_t.model_dump(), None, regimes)
    for line in phash_data.decode("utf-8").splitlines()[1:]:
        parts = line.split(",")
        ka, kb = (parts[0], parts[1]), (parts[2], parts[3])
        if ka in base_vectors and kb in base_vectors:
            pair_cos[(ka, kb)] = float(
                np.dot(base_vectors[ka].astype(np.float64), base_vectors[kb].astype(np.float64))
            )
    phash_summary, phash_data = phash_only_stage(view, small_t.model_dump(), pair_cos, regimes)
    files[phash_summary.file] = phash_data
    log("source probe: features of the released images")
    table = probe_table(view, data / view.manifest.images_dir)
    probe_bytes = parquet_bytes(table)
    files[(ARTIFACTS / "source-probe-features.parquet").as_posix()] = probe_bytes
    columns = table.to_pydict()
    probe = run_probe(
        {name: columns[name] for name in FEATURES},
        columns["source"],
        columns["global_id"],
        columns["constraint_group"],
        seed=0,
    )
    log("packages and their independent validation")
    package_regimes = {
        "A0": view.schemes["A0"],
        "A1": view.schemes["A1"],
        **{f"B-{s}": view.schemes[f"B-{s}"] for s in slugs},
        **design_splits,
        **{k: v for k, v in held_splits.items() if k.startswith("B-natural-")},
    }
    if packages is not None:
        unknown = sorted(set(packages) - set(package_regimes))
        if unknown:
            raise RunError(f"unknown package schemes: {', '.join(unknown)}")
        package_regimes = {k: v for k, v in package_regimes.items() if k in packages}
    export = export_stage(
        view, data, package_regimes, ultralytics_python=ultralytics_python, root=root, log=log
    )
    m6 = load_json(root / M6_RECORD)
    validation = read_validation(root)
    negative = negatives(root, view)
    natural_differs = [
        s for s in slugs if held_splits[f"B-natural-{s}"] != held_splits[f"B-strict-{s}"]
    ]
    blocking = blockers(
        m6_verdict=str(m6["verdict"]),
        reproduced=reproduction.ok,
        exports_ok=all(
            p.internal_ok and (p.ultralytics is None or p.ultralytics.ok) for p in export.packages
        ),
        fatal=labels.by_category["FATAL"],
        designs=designs,
        held_out=held,
    )
    limits = limitations(
        validation_status=validation.status,
        representation=representation,
        giant=giant,
        designs=designs,
        labels=labels,
        negatives=negative,
        phash=phash_summary,
        probe=probe,
        held_out=held,
    )
    decided = verdict(blocking, limits)
    est = estimand(view)
    texts = answer_texts(
        m6_verdict=str(m6["verdict"]),
        export=export,
        labels=labels,
        estimand=est,
        designs=designs,
        representation=representation,
        giant=giant,
        probe=probe,
        held_out=held,
        validation_status=validation.status,
        verdict=decided,
        blockers=blocking,
    )
    inputs = {
        rel: sha256_file(root / rel)
        for rel in (
            "artifacts/m3/audit.json",
            "artifacts/m3/leakage-groups.parquet",
            "artifacts/m3/duplicate-pairs.parquet",
            "artifacts/m3/review-candidates.csv",
            "artifacts/m4/review-required.csv",
            M6_RECORD,
            "configs/release.yaml",
            "configs/dedup.yaml",
            "configs/taxonomy.yaml",
            *(
                f"manifests/releases/{view.config.version}/{name}"
                for name in (ITEMS, ANNOTATIONS, RELEASE, "excluded.parquet")
            ),
            *(e.file for e in view.manifest.splits),
        )
    }
    readiness = Readiness(
        provenance=Provenance(
            command="openinspect readiness compute",
            code_commit=code[0],
            code_dirty=code[1],
            release=view.config.version,
            release_manifest_sha256=sha256_file(release_dir(root, view.config.version) / RELEASE),
            design_seeds=list(DESIGN_SEEDS),
            split_seed=view.config.seed,
            probe_seed=0,
            models=[_pin(config, "dinov2-small"), _pin(config, "dinov2-base")],
            thresholds={
                "dinov2-small": {"family": small_t.family, "near": small_t.near},
                "dinov2-base": {"family": base_t.family, "near": base_t.near},
            },
            inputs=dict(sorted(inputs.items())),
            outputs={path: sha256_bytes(blob) for path, blob in sorted(files.items())},
        ),
        human_validation=validation.record(),
        m6_verdict=str(m6["verdict"]),
        reproduction=ReproductionRecord(
            group_keys_match=reproduction.group_keys_match,
            schemes_match=reproduction.schemes_match,
            split_files_match=reproduction.split_files_match,
            small_components_match_m3=small.components == view.components,
        ),
        estimand=est,
        designs=designs,
        held_out=held,
        representation=representation,
        giant=giant,
        labels=labels,
        labels_file=(ARTIFACTS / "release-label-findings.csv").as_posix(),
        labels_sha256=sha256_bytes(files[(ARTIFACTS / "release-label-findings.csv").as_posix()]),
        negatives=negative,
        phash_only=phash_summary,
        probe=probe,
        probe_features_file=(ARTIFACTS / "source-probe-features.parquet").as_posix(),
        probe_features_sha256=sha256_bytes(probe_bytes),
        export=export,
        blockers=blocking,
        limitations=limits,
        verdict=decided,  # type: ignore[arg-type]
        verdict_rule=VERDICT_RULE,
        answers=answers(texts),
        plan=plan(DESIGN_SEEDS, slugs, natural_differs, view.config.version),
    )
    return Outputs(files, readiness)
