"""M7 evaluation: every trained checkpoint under one local protocol. Nothing is trained.

Run it in a separate environment with Ultralytics 8.3.0, the version that trained the checkpoints
(Ultralytics is AGPL-3.0 and never a project dependency), for example::

    <venv>/python scripts/m7_evaluate.py --data-dir C:/data/openinspect

Stage ``infer``: for every checkpoint of ``reports/m7/final_run_manifest.json`` and every
training-noise replicate of ``reports/m7/checkpoint_manifest.csv`` (each file checked against its
recorded SHA-256), the test split of the package of its design is extracted to a temporary folder
(the package ZIP is checked against the SHA-256 recorded in M5.5) and validated with Ultralytics'
DetectionValidator: imgsz 640, conf 0.001, iou 0.7, max_det 300, rect batches of 32, CPU, FP32.
Each image's detections (box, confidence, class, true-positive flags at IoU 0.50:0.95) and its
ground truth are stored in ``<data>/m7/eval/``; the temporary images are deleted.

Stage ``analyze``: metrics are recomputed from the stored detections with Ultralytics'
``ap_per_class`` (checked against the validator's own numbers) for whole test populations and for
subsets (probe and control from the committed role files, sources), and paired differences get
bootstrap confidence intervals that resample whole A1 constraint groups of the common test
population (1,000 resamples, seed 0), as frozen in the M7 plan. Writes ``reports/m7/``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import sys
import time
import zipfile
import zlib
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parents[1]
REPORTS = REPO / "reports" / "m7"
FIGURES = REPORTS / "figures"
RELEASE = REPO / "manifests" / "releases" / "v0.1"
EXPERIMENTS = REPO / "manifests" / "experiments" / "v0.1"
READINESS = REPO / "artifacts" / "m5_5" / "readiness.json"

PROTOCOL = {
    "imgsz": 640,
    "conf": 0.001,
    "iou": 0.7,
    "max_det": 300,
    "batch": 32,
    "rect": True,
    "half": False,
    "device": "cpu",
    "split": "test",
}
BOOTSTRAP = 1000
BOOTSTRAP_SEED = 0
CLASSES = ("short", "open", "mouse_bite", "spurious_copper")
SOURCES = ("dspcbsd-plus", "pcb-defect", "pcb-ind")
NIOU = 10
Json = dict[str, Any]


# --------------------------------------------------------------------------- the populations


def package_for(run: str) -> str:
    """The M5.5 package (scheme) whose test split is the run's test population."""
    if run.startswith(("C0-d", "C1-d")):
        return f"C0-d{run[4]}"  # C0 and C1 of a design share the test split (checked)
    if run.startswith("A0"):
        return "A0"
    if run.startswith("A1"):
        return "A1"
    for source in SOURCES:
        if run.startswith((f"B-strict-{source}", f"B-natural-{source}")):
            return f"B-{source}"  # strict and natural hold the same source out (checked)
    raise ValueError(f"no test population for {run}")


def population_of(run: str) -> str:
    scheme = package_for(run)
    return {f"C0-d{d}": f"D{d}" for d in (0, 1, 2)}.get(scheme, scheme)


@dataclass(frozen=True)
class Model:
    name: str  # run id, or noise/<identity>__<job>
    file: Path
    sha256: str
    job_id: str
    purpose: str  # planned run / training-noise replicate


def models(data_dir: Path) -> list[Model]:
    manifest = json.loads((REPORTS / "final_run_manifest.json").read_text(encoding="utf-8"))
    out = []
    for run in manifest["runs"]:
        out.append(
            Model(
                run["intended_run_name"],
                data_dir / "models" / "m7" / f"{run['intended_run_name']}.pt",
                run["checkpoint_sha256"],
                run["job_id"],
                "planned run",
            )
        )
    with (REPORTS / "checkpoint_manifest.csv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["purpose"] != "planned run":
                out.append(
                    Model(
                        row["file"].removesuffix(".pt"),
                        data_dir / "models" / "m7" / row["file"],
                        row["sha256"],
                        row["job_id"],
                        row["purpose"],
                    )
                )
    return out


def identity(model: Model) -> str:
    """The run a model trains, also for a replicate (noise/C1-d0-s0__r1 -> C1-d0-s0)."""
    return model.name.split("/")[-1].split("__")[0]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_zip(data_dir: Path, scheme: str) -> Path:
    path = data_dir / "exports" / "v0.1" / f"openinspect-trust-v0.1-{scheme}-yolo.zip"
    recorded = {
        p["scheme"]: p["sha256"]
        for p in json.loads(READINESS.read_text(encoding="utf-8"))["export"]["packages"]
    }
    if sha256_file(path) != recorded[scheme]:
        raise RuntimeError(f"{path.name} differs from the package validated in M5.5")
    return path


def test_members(path: Path) -> dict[str, bytes]:
    """Label file bytes of the test split, by global id."""
    with zipfile.ZipFile(path) as archive:
        return {
            Path(n).stem: archive.read(n)
            for n in archive.namelist()
            if n.startswith("labels/test/") and n.endswith(".txt")
        }


def extract_test(path: Path, folder: Path) -> Path:
    if folder.exists():
        shutil.rmtree(folder)
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if name.startswith(("images/test/", "labels/test/")) and not name.endswith("/"):
                target = folder / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(name))
    yaml_text = (
        f"path: {folder.as_posix()}\ntrain: images/test\nval: images/test\ntest: images/test\n"
        f"nc: {len(CLASSES)}\nnames:\n" + "".join(f"  {k}: {n}\n" for k, n in enumerate(CLASSES))
    )
    (folder / "data.yaml").write_text(yaml_text, encoding="utf-8")
    return folder / "data.yaml"


# ---------------------------------------------------------------------------------- inference


def run_inference(data_dir: Path, selected: Sequence[str] | None) -> None:
    import torch
    from ultralytics import YOLO
    from ultralytics.models.yolo.detect import DetectionValidator
    from ultralytics.utils import SETTINGS

    SETTINGS.update({"sync": False})  # no usage analytics from this evaluation

    class RecordingValidator(DetectionValidator):  # type: ignore[misc]
        """Ultralytics' update_metrics, unchanged, that also keeps every image's detections."""

        def init_metrics(self, model: Any) -> None:
            super().init_metrics(model)
            self.records: list[Json] = []

        def update_metrics(self, preds: Any, batch: Any) -> None:
            for si, pred in enumerate(preds):
                self.seen += 1
                npr = len(pred)
                stat = {
                    "conf": torch.zeros(0, device=self.device),
                    "pred_cls": torch.zeros(0, device=self.device),
                    "tp": torch.zeros(npr, self.niou, dtype=torch.bool, device=self.device),
                }
                pbatch = self._prepare_batch(si, batch)
                cls, bbox = pbatch.pop("cls"), pbatch.pop("bbox")
                nl = len(cls)
                stat["target_cls"] = cls
                stat["target_img"] = cls.unique()
                boxes = torch.zeros((0, 4))
                if npr:
                    predn = self._prepare_pred(pred, pbatch)
                    stat["conf"] = predn[:, 4]
                    stat["pred_cls"] = predn[:, 5]
                    boxes = predn[:, :4]
                    if nl:
                        stat["tp"] = self._process_batch(predn, bbox, cls)
                if npr or nl:
                    for k in self.stats:
                        self.stats[k].append(stat[k])
                self.records.append(
                    {
                        "image": Path(batch["im_file"][si]).stem,
                        "conf": stat["conf"].cpu().numpy().astype(np.float32),
                        "cls": stat["pred_cls"].cpu().numpy().astype(np.int8),
                        "tp": stat["tp"].cpu().numpy().astype(bool),
                        "boxes": boxes.cpu().numpy().astype(np.float32),
                        "target_cls": cls.cpu().numpy().astype(np.int8),
                    }
                )

    out = data_dir / "m7" / "eval"
    out.mkdir(parents=True, exist_ok=True)
    work = data_dir / "m7" / "tmp"
    by_population: dict[str, list[Model]] = {}
    for model in models(data_dir):
        if selected and model.name not in selected:
            continue
        by_population.setdefault(package_for(identity(model)), []).append(model)
    torch.set_num_threads(max(1, os.cpu_count() or 1))
    for scheme, members in sorted(by_population.items()):
        zip_path = package_zip(data_dir, scheme)
        labels = test_members(zip_path)
        for other in {package_for(identity(m)) for m in members} | _twins(scheme):
            if other != scheme and test_members(package_zip(data_dir, other)) != labels:
                raise RuntimeError(f"the test splits of {scheme} and {other} differ")
        yaml = extract_test(zip_path, work / scheme)
        try:
            for model in members:
                if sha256_file(model.file) != model.sha256:
                    raise RuntimeError(f"{model.file.name} differs from checkpoint_manifest.csv")
                target = out / f"{model.name.replace('/', '__')}.parquet"
                started = time.time()
                yolo = YOLO(str(model.file))
                names = {int(k): v for k, v in yolo.model.names.items()}
                if [names[k] for k in sorted(names)] != list(CLASSES):
                    raise RuntimeError(
                        f"{model.name}: class order {names} differs from the release"
                    )
                args = {
                    **yolo.overrides,
                    "rect": True,
                    **PROTOCOL,
                    "data": str(yaml),
                    "plots": False,
                    "save_json": False,
                    "verbose": False,
                    "workers": 0,
                    "project": str(data_dir / "m7" / "runs"),
                    "name": model.name.replace("/", "__"),
                    "exist_ok": True,
                    "mode": "val",
                }
                validator = RecordingValidator(args=args, _callbacks=yolo.callbacks)
                validator(model=yolo.model)
                box = validator.metrics.box
                write_records(target, validator.records, model, scheme, box)
                print(
                    f"{model.name:32} {scheme:16} images {len(validator.records):5} "
                    f"mAP50-95 {box.map:.4f} mAP50 {box.map50:.4f} ({time.time() - started:.0f}s)"
                )
        finally:
            shutil.rmtree(work / scheme, ignore_errors=True)


def _twins(scheme: str) -> set[str]:
    """Packages whose test split must equal this one's."""
    if scheme.startswith("C0-d"):
        return {scheme.replace("C0", "C1")}
    if scheme.startswith("B-"):
        source = scheme.removeprefix("B-")
        return {f"B-natural-{source}"}
    return set()


def write_records(
    target: Path, records: Sequence[Json], model: Model, scheme: str, box: Any
) -> None:
    det_image, conf, cls, tp, boxes, gt_image, gt_cls = [], [], [], [], [], [], []
    for r in records:
        n = len(r["conf"])
        det_image += [r["image"]] * n
        conf.append(r["conf"])
        cls.append(r["cls"])
        bits = (
            (r["tp"].astype(np.uint16) << np.arange(NIOU, dtype=np.uint16)).sum(1)
            if n
            else np.zeros(0, np.uint16)
        )
        tp.append(bits.astype(np.uint16))
        boxes.append(r["boxes"].reshape(-1, 4))
        gt_image += [r["image"]] * len(r["target_cls"])
        gt_cls.append(r["target_cls"])
    b = np.concatenate(boxes) if boxes else np.zeros((0, 4), np.float32)
    detections = pa.table(
        {
            "image": pa.array(det_image, pa.string()),
            "conf": pa.array(np.concatenate(conf) if conf else [], pa.float32()),
            "cls": pa.array(np.concatenate(cls) if cls else [], pa.int8()),
            "tp_bits": pa.array(np.concatenate(tp) if tp else [], pa.uint16()),
            "x1": pa.array(b[:, 0], pa.float32()),
            "y1": pa.array(b[:, 1], pa.float32()),
            "x2": pa.array(b[:, 2], pa.float32()),
            "y2": pa.array(b[:, 3], pa.float32()),
        }
    )
    targets = pa.table(
        {
            "image": pa.array(gt_image, pa.string()),
            "cls": pa.array(np.concatenate(gt_cls) if gt_cls else [], pa.int8()),
        }
    )
    images = pa.table({"image": pa.array([r["image"] for r in records], pa.string())})
    meta = {
        "model": model.name,
        "job_id": model.job_id,
        "checkpoint_sha256": model.sha256,
        "package": scheme,
        "protocol": json.dumps(PROTOCOL),
        "validator_map50_95": f"{box.map:.10f}",
        "validator_map50": f"{box.map50:.10f}",
        "validator_mp": f"{box.mp:.10f}",
        "validator_mr": f"{box.mr:.10f}",
    }
    pq.write_table(detections.replace_schema_metadata(meta), target)
    pq.write_table(targets, target.with_suffix(".targets.parquet"))
    pq.write_table(images, target.with_suffix(".images.parquet"))


# ----------------------------------------------------------------------------------- metrics


@dataclass
class Predictions:
    images: list[str]  # every image of the population, in validator order
    index: dict[str, int]
    det_img: np.ndarray  # image index of each detection
    conf: np.ndarray
    cls: np.ndarray
    tp: np.ndarray  # (n, 10) bool
    gt_img: np.ndarray
    gt_cls: np.ndarray
    validator: dict[str, float]


def load(path: Path) -> Predictions:
    det = pq.read_table(path)
    meta = {k.decode(): v.decode() for k, v in (det.schema.metadata or {}).items()}
    gt = pq.read_table(path.with_suffix(".targets.parquet")).to_pydict()
    images = pq.read_table(path.with_suffix(".images.parquet")).to_pydict()["image"]
    index = {g: k for k, g in enumerate(images)}
    d = det.to_pydict()
    bits = np.asarray(d["tp_bits"], dtype=np.uint16)
    return Predictions(
        images,
        index,
        np.asarray([index[g] for g in d["image"]], dtype=np.int64),
        np.asarray(d["conf"], dtype=np.float64),
        np.asarray(d["cls"], dtype=np.int64),
        ((bits[:, None] >> np.arange(NIOU, dtype=np.uint16)) & 1).astype(bool),
        np.asarray([index[g] for g in gt["image"]], dtype=np.int64),
        np.asarray(gt["cls"], dtype=np.int64),
        {
            k.removeprefix("validator_"): float(v)
            for k, v in meta.items()
            if k.startswith("validator_")
        },
    )


def metrics(p: Predictions, weights: np.ndarray) -> Json:
    """Ultralytics' ap_per_class on the images with their multiplicities (a bootstrap resample)."""
    from ultralytics.utils.metrics import ap_per_class

    w_det = weights[p.det_img]
    w_gt = weights[p.gt_img]
    det = np.repeat(np.arange(len(p.conf)), w_det)
    gt = np.repeat(np.arange(len(p.gt_cls)), w_gt)
    target_cls = p.gt_cls[gt]
    if len(target_cls) == 0:
        return {"mAP50_95": float("nan"), "mAP50": float("nan")}
    _, _, prec, rec, _f1, ap, classes, *_ = ap_per_class(
        p.tp[det], p.conf[det], p.cls[det], target_cls
    )
    out: Json = {
        "mAP50_95": float(ap.mean()) if len(ap) else 0.0,
        "mAP50": float(ap[:, 0].mean()) if len(ap) else 0.0,
        "precision": float(prec.mean()) if len(prec) else 0.0,
        "recall": float(rec.mean()) if len(rec) else 0.0,
    }
    mp, mr = out["precision"], out["recall"]
    out["F1"] = 2 * mp * mr / (mp + mr) if mp + mr else 0.0
    for k, c in enumerate(classes):
        out[f"AP50_95_{CLASSES[c]}"] = float(ap[k].mean())
        out[f"AP50_{CLASSES[c]}"] = float(ap[k, 0])
    out["n_images"] = int(weights.sum())
    out["n_boxes"] = len(target_cls)
    return out


def subset_weights(p: Predictions, members: set[str]) -> np.ndarray:
    return np.asarray([1 if g in members else 0 for g in p.images], dtype=np.int64)


# ------------------------------------------------------------------------------------- design


def roles(design: int) -> dict[str, str]:
    with (EXPERIMENTS / f"C-design{design}-roles.csv").open(encoding="utf-8", newline="") as handle:
        return {r["id"]: r["role"] for r in csv.DictReader(handle)}


def release_items() -> tuple[dict[str, str], dict[str, str]]:
    table = pq.read_table(
        RELEASE / "items.parquet", columns=["global_id", "source", "constraint_group"]
    ).to_pydict()
    source = dict(zip(table["global_id"], table["source"], strict=True))
    group = dict(zip(table["global_id"], table["constraint_group"], strict=True))
    return source, group


def resamples(
    images: Sequence[str], members: set[str], group: Mapping[str, str], name: str
) -> np.ndarray:
    """(BOOTSTRAP, len(images)) multiplicities: whole A1 constraint groups drawn with replacement."""
    inside = [g for g in images if g in members]
    keys = sorted({group[g] for g in inside})
    position = {k: i for i, k in enumerate(keys)}
    by_group = np.zeros((len(keys), len(images)), dtype=np.int64)
    for col, g in enumerate(images):
        if g in members:
            by_group[position[group[g]], col] = 1
    rng = np.random.default_rng([BOOTSTRAP_SEED, zlib.crc32(name.encode("utf-8"))])
    draws = rng.integers(0, len(keys), size=(BOOTSTRAP, len(keys)))
    counts = np.zeros((BOOTSTRAP, len(keys)), dtype=np.int64)
    for b in range(BOOTSTRAP):
        np.add.at(counts[b], draws[b], 1)
    return counts @ by_group


def ci(values: np.ndarray) -> tuple[float, float]:
    values = values[np.isfinite(values)]
    return float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))


# ----------------------------------------------------------------------------------- analysis


def analyze(data_dir: Path) -> None:
    eval_dir = data_dir / "m7" / "eval"
    all_models = models(data_dir)
    preds = {m.name: load(eval_dir / f"{m.name.replace('/', '__')}.parquet") for m in all_models}
    purpose = {m.name: m.purpose for m in all_models}
    source, group = release_items()

    # 1. the recomputation equals the validator
    for name, p in preds.items():
        full = metrics(p, np.ones(len(p.images), dtype=np.int64))
        if (
            abs(full["mAP50_95"] - p.validator["map50_95"]) > 1e-9
            or abs(full["mAP50"] - p.validator["map50"]) > 1e-9
        ):
            raise RuntimeError(f"{name}: recomputed metrics differ from the validator")

    # 2. populations and subsets
    def subsets(name: str) -> dict[str, set[str]]:
        p = preds[name]
        pop = population_of(identity_name(name))
        out = {"overall": set(p.images)}
        for s in SOURCES:
            members = {g for g in p.images if source[g] == s}
            if members and len(members) < len(p.images):
                out[f"source:{s}"] = members
        if pop.startswith("D"):
            r = roles(int(pop[1]))
            out["probe"] = {g for g in p.images if r.get(g) == "probe"}
            out["control"] = {g for g in p.images if r.get(g) == "control"}
            if out["probe"] | out["control"] != set(p.images):
                raise RuntimeError(f"{name}: the test set is not exactly the probes and controls")
        return out

    rows: list[Json] = []
    for name in preds:
        for subset, members in subsets(name).items():
            m = metrics(preds[name], subset_weights(preds[name], members))
            rows.append(
                {
                    "model": name,
                    "purpose": purpose[name],
                    "population": population_of(identity_name(name)),
                    "subset": subset,
                    **m,
                }
            )
    table = {(r["model"], r["subset"]): r for r in rows}

    # 3. paired comparisons with bootstrap
    comparisons: list[tuple[str, str, str, str]] = []  # (label, a, b, population)
    for s in (0, 1, 2):
        comparisons.append((f"D0 seed {s}: C0 - C1", f"C0-d0-s{s}", f"C1-d0-s{s}", "D0"))
    for d in (1, 2):
        comparisons.append((f"D{d} seed 0: C0 - C1", f"C0-d{d}-s0", f"C1-d{d}-s0", f"D{d}"))
    for held in ("dspcbsd-plus", "pcb-ind"):
        comparisons.append(
            (
                f"B {held}: natural - strict",
                f"B-natural-{held}-s0",
                f"B-strict-{held}-s0",
                f"B-{held}",
            )
        )
    noise = [n for n in preds if purpose[n] != "planned run"]
    for n in noise:
        ident = identity_name(n)
        twin = ident if ident in preds else None
        partners = [m for m in noise if m != n and identity_name(m) == ident]
        if twin is not None:
            comparisons.append(
                (f"noise {ident}: planned - replicate", twin, n, population_of(ident))
            )
        elif partners and n < partners[0]:
            comparisons.append(
                (f"noise {ident}: replicate - replicate", n, partners[0], population_of(ident))
            )

    boot_rows: list[Json] = []
    cache: dict[tuple[str, str], tuple[list[str], np.ndarray]] = {}
    deltas_by: dict[tuple[str, str, str], np.ndarray] = {}
    for label, a, b, pop in comparisons:
        pa_, pb = preds[a], preds[b]
        if pa_.images != pb.images and sorted(pa_.images) != sorted(pb.images):
            raise RuntimeError(f"{label}: the two models were not evaluated on the same images")
        for subset, members in subsets(a).items():
            if subset.startswith("source:"):
                continue  # point estimates only; the intervals cover the population and its parts
            key = (pop, subset)
            if key not in cache:
                cache[key] = (
                    list(pa_.images),
                    resamples(pa_.images, members, group, f"{pop}/{subset}"),
                )
            first_order, matrix = cache[key]
            column = {g: i for i, g in enumerate(first_order)}
            w = matrix[:, [column[g] for g in pa_.images]]  # the same resamples, in a's order
            order = [pb.index[g] for g in pa_.images]
            da, db = np.empty(BOOTSTRAP), np.empty(BOOTSTRAP)
            ea, eb = np.empty(BOOTSTRAP), np.empty(BOOTSTRAP)
            for k in range(BOOTSTRAP):
                wb = np.zeros(len(pb.images), dtype=np.int64)
                wb[order] = w[k]
                ma, mb = metrics(pa_, w[k]), metrics(pb, wb)
                da[k], db[k] = ma["mAP50_95"], mb["mAP50_95"]
                ea[k], eb[k] = ma["mAP50"], mb["mAP50"]
            deltas_by[(label, subset, "mAP50_95")] = da - db
            deltas_by[(label, subset, "mAP50")] = ea - eb
            for metric, delta in (("mAP50_95", da - db), ("mAP50", ea - eb)):
                point = table[(a, subset)][metric] - table[(b, subset)][metric]
                low, high = ci(delta)
                boot_rows.append(
                    {
                        "comparison": label,
                        "model_a": a,
                        "model_b": b,
                        "population": pop,
                        "subset": subset,
                        "metric": metric,
                        "delta": point,
                        "ci_low": low,
                        "ci_high": high,
                        "bootstrap_sd": float(np.nanstd(delta)),
                        "resamples": BOOTSTRAP,
                        "rng_seed": BOOTSTRAP_SEED,
                        "resampled_unit": "A1 constraint group",
                        "groups": len({group[g] for g in members}),
                        "images": len(members),
                    }
                )
            print(f"bootstrap {label} / {subset} done", file=sys.stderr)
    # the three-seed mean of D0, on the same resamples
    for subset in ("overall", "probe", "control"):
        for metric in ("mAP50_95", "mAP50"):
            parts = [deltas_by[(f"D0 seed {s}: C0 - C1", subset, metric)] for s in (0, 1, 2)]
            mean = np.mean(parts, axis=0)
            point = float(
                np.mean(
                    [
                        table[(f"C0-d0-s{s}", subset)][metric]
                        - table[(f"C1-d0-s{s}", subset)][metric]
                        for s in (0, 1, 2)
                    ]
                )
            )
            deltas_by[("D0 mean of seeds 0-2: C0 - C1", subset, metric)] = mean
            low, high = ci(mean)
            boot_rows.append(
                {
                    "comparison": "D0 mean of seeds 0-2: C0 - C1",
                    "model_a": "C0-d0-s0..2",
                    "model_b": "C1-d0-s0..2",
                    "population": "D0",
                    "subset": subset,
                    "metric": metric,
                    "delta": point,
                    "ci_low": low,
                    "ci_high": high,
                    "bootstrap_sd": float(np.nanstd(mean)),
                    "resamples": BOOTSTRAP,
                    "rng_seed": BOOTSTRAP_SEED,
                    "resampled_unit": "A1 constraint group (same resamples for the three seeds)",
                    "groups": next(
                        r["groups"]
                        for r in boot_rows
                        if r["population"] == "D0" and r["subset"] == subset
                    ),
                    "images": next(
                        r["images"]
                        for r in boot_rows
                        if r["population"] == "D0" and r["subset"] == subset
                    ),
                }
            )
    # probe minus control: the two subsets hold different constraint groups and are resampled
    # independently, so their draws combine into the interval of the difference in differences
    point_of = {(r["comparison"], r["subset"], r["metric"]): r["delta"] for r in boot_rows}
    labels = [f"D0 seed {s}: C0 - C1" for s in (0, 1, 2)]
    labels += ["D0 mean of seeds 0-2: C0 - C1", "D1 seed 0: C0 - C1", "D2 seed 0: C0 - C1"]
    for label in labels:
        for metric in ("mAP50_95", "mAP50"):
            draws = deltas_by[(label, "probe", metric)] - deltas_by[(label, "control", metric)]
            low, high = ci(draws)
            boot_rows.append(
                {
                    "comparison": label,
                    "model_a": "probe",
                    "model_b": "control",
                    "population": label.split()[0],
                    "subset": "probe - control",
                    "metric": metric,
                    "delta": point_of[(label, "probe", metric)]
                    - point_of[(label, "control", metric)],
                    "ci_low": low,
                    "ci_high": high,
                    "bootstrap_sd": float(np.nanstd(draws)),
                    "resamples": BOOTSTRAP,
                    "rng_seed": BOOTSTRAP_SEED,
                    "resampled_unit": "A1 constraint group, probes and controls independently",
                    "groups": "",
                    "images": "",
                }
            )
    write_outputs(rows, boot_rows, preds)


def identity_name(name: str) -> str:
    return name.split("/")[-1].split("__")[0]


# ------------------------------------------------------------------------------------ outputs


METRIC_FIELDS = (
    "mAP50_95",
    "mAP50",
    "precision",
    "recall",
    "F1",
    *(f"AP50_95_{c}" for c in CLASSES),
    *(f"AP50_{c}" for c in CLASSES),
)


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {k: (round(v, 6) if isinstance(v, float) else v) for k, v in row.items()}
            )


def write_outputs(
    rows: Sequence[Json], boot: Sequence[Json], preds: Mapping[str, Predictions]
) -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    FIGURES.mkdir(parents=True, exist_ok=True)
    table = {(r["model"], r["subset"]): r for r in rows}
    base = ("model", "purpose", "population", "subset", "n_images", "n_boxes")
    _write_csv(REPORTS / "final_metrics.csv", rows, (*base, *METRIC_FIELDS))
    _write_csv(
        REPORTS / "bootstrap_results.csv",
        boot,
        (
            "comparison",
            "model_a",
            "model_b",
            "population",
            "subset",
            "metric",
            "delta",
            "ci_low",
            "ci_high",
            "bootstrap_sd",
            "resamples",
            "rng_seed",
            "resampled_unit",
            "groups",
            "images",
        ),
    )
    bkey = {(r["comparison"], r["subset"], r["metric"]): r for r in boot}

    seed_rows = []
    for s in (0, 1, 2):
        a, b = table[(f"C0-d0-s{s}", "overall")], table[(f"C1-d0-s{s}", "overall")]
        r = bkey[(f"D0 seed {s}: C0 - C1", "overall", "mAP50_95")]
        seed_rows.append(
            {
                "seed": s,
                **{f"C0_{k}": a[k] for k in ("mAP50_95", "mAP50", "precision", "recall", "F1")},
                **{f"C1_{k}": b[k] for k in ("mAP50_95", "mAP50", "precision", "recall", "F1")},
                **{
                    f"delta_{k}": a[k] - b[k]
                    for k in ("mAP50_95", "mAP50", "precision", "recall", "F1")
                },
                "delta_mAP50_95_ci_low": r["ci_low"],
                "delta_mAP50_95_ci_high": r["ci_high"],
            }
        )
    deltas = np.array([r["delta_mAP50_95"] for r in seed_rows])
    seed_rows.append(
        {
            "seed": "mean",
            "delta_mAP50_95": float(deltas.mean()),
            "delta_mAP50": float(np.mean([r["delta_mAP50"] for r in seed_rows[:3]])),
            "delta_mAP50_95_ci_low": bkey[("D0 mean of seeds 0-2: C0 - C1", "overall", "mAP50_95")][
                "ci_low"
            ],
            "delta_mAP50_95_ci_high": bkey[
                ("D0 mean of seeds 0-2: C0 - C1", "overall", "mAP50_95")
            ]["ci_high"],
        }
    )
    seed_rows.append(
        {
            "seed": "sd (between seeds)",
            "delta_mAP50_95": float(deltas.std(ddof=1)),
            "delta_mAP50": float(np.std([r["delta_mAP50"] for r in seed_rows[:3]], ddof=1)),
        }
    )
    seed_fields = [
        "seed",
        *(
            f"{c}_{k}"
            for c in ("C0", "C1", "delta")
            for k in ("mAP50_95", "mAP50", "precision", "recall", "F1")
        ),
        "delta_mAP50_95_ci_low",
        "delta_mAP50_95_ci_high",
    ]
    _write_csv(REPORTS / "d0_seed_results.csv", seed_rows, seed_fields)

    pc_rows = []
    for design, seeds in ((0, (0, 1, 2)), (1, (0,)), (2, (0,))):
        for s in seeds:
            for subset in ("overall", "probe", "control"):
                a, b = table[(f"C0-d{design}-s{s}", subset)], table[(f"C1-d{design}-s{s}", subset)]
                r = bkey[(f"D{design} seed {s}: C0 - C1", subset, "mAP50_95")]
                pc_rows.append(
                    {
                        "design": design,
                        "seed": s,
                        "subset": subset,
                        "images": a["n_images"],
                        "boxes": a["n_boxes"],
                        "C0_mAP50_95": a["mAP50_95"],
                        "C1_mAP50_95": b["mAP50_95"],
                        "delta_mAP50_95": a["mAP50_95"] - b["mAP50_95"],
                        "ci_low": r["ci_low"],
                        "ci_high": r["ci_high"],
                        "C0_mAP50": a["mAP50"],
                        "C1_mAP50": b["mAP50"],
                        "delta_mAP50": a["mAP50"] - b["mAP50"],
                    }
                )
    for subset in ("overall", "probe", "control"):
        r = bkey[("D0 mean of seeds 0-2: C0 - C1", subset, "mAP50_95")]
        pc_rows.append(
            {
                "design": 0,
                "seed": "mean",
                "subset": subset,
                "delta_mAP50_95": r["delta"],
                "ci_low": r["ci_low"],
                "ci_high": r["ci_high"],
                "delta_mAP50": bkey[("D0 mean of seeds 0-2: C0 - C1", subset, "mAP50")]["delta"],
            }
        )
    did_specs: list[tuple[str, int, object]] = [
        *((f"D0 seed {s}: C0 - C1", 0, s) for s in (0, 1, 2)),
        ("D0 mean of seeds 0-2: C0 - C1", 0, "mean"),
        ("D1 seed 0: C0 - C1", 1, 0),
        ("D2 seed 0: C0 - C1", 2, 0),
    ]
    for label, design, seed_label in did_specs:
        r = bkey[(label, "probe - control", "mAP50_95")]
        pc_rows.append(
            {
                "design": design,
                "seed": seed_label,
                "subset": "probe - control",
                "delta_mAP50_95": r["delta"],
                "ci_low": r["ci_low"],
                "ci_high": r["ci_high"],
                "delta_mAP50": bkey[(label, "probe - control", "mAP50")]["delta"],
            }
        )
    _write_csv(
        REPORTS / "probe_control_results.csv",
        pc_rows,
        (
            "design",
            "seed",
            "subset",
            "images",
            "boxes",
            "C0_mAP50_95",
            "C1_mAP50_95",
            "delta_mAP50_95",
            "ci_low",
            "ci_high",
            "C0_mAP50",
            "C1_mAP50",
            "delta_mAP50",
        ),
    )

    rep_rows = []
    for design in (1, 2):
        for subset in ("overall", "probe", "control"):
            a, b = table[(f"C0-d{design}-s0", subset)], table[(f"C1-d{design}-s0", subset)]
            r50_95 = bkey[(f"D{design} seed 0: C0 - C1", subset, "mAP50_95")]
            r50 = bkey[(f"D{design} seed 0: C0 - C1", subset, "mAP50")]
            rep_rows.append(
                {
                    "design": design,
                    "subset": subset,
                    "images": a["n_images"],
                    "delta_mAP50_95": a["mAP50_95"] - b["mAP50_95"],
                    "ci_low_mAP50_95": r50_95["ci_low"],
                    "ci_high_mAP50_95": r50_95["ci_high"],
                    "delta_mAP50": a["mAP50"] - b["mAP50"],
                    "ci_low_mAP50": r50["ci_low"],
                    "ci_high_mAP50": r50["ci_high"],
                    **{
                        f"delta_AP50_95_{c}": a.get(f"AP50_95_{c}", float("nan"))
                        - b.get(f"AP50_95_{c}", float("nan"))
                        for c in CLASSES
                    },
                }
            )
    _write_csv(
        REPORTS / "replication_results.csv",
        rep_rows,
        (
            "design",
            "subset",
            "images",
            "delta_mAP50_95",
            "ci_low_mAP50_95",
            "ci_high_mAP50_95",
            "delta_mAP50",
            "ci_low_mAP50",
            "ci_high_mAP50",
            *(f"delta_AP50_95_{c}" for c in CLASSES),
        ),
    )

    src_rows = []
    for held in SOURCES:
        for regime in ("strict", "natural"):
            name = f"B-{regime}-{held}-s0"
            if (name, "overall") in table:
                r = table[(name, "overall")]
                src_rows.append(
                    {
                        "held_out": held,
                        "regime": f"B-{regime}",
                        "model": name,
                        "test_images": r["n_images"],
                        "test_boxes": r["n_boxes"],
                        **{k: r[k] for k in METRIC_FIELDS if k in r},
                    }
                )
        for ref in ("A1-s0", "A0-s0"):
            if (ref, f"source:{held}") in table:
                r = table[(ref, f"source:{held}")]
                src_rows.append(
                    {
                        "held_out": held,
                        "regime": f"{ref.split('-')[0]} (in-distribution reference, different test items)",
                        "model": ref,
                        "test_images": r["n_images"],
                        "test_boxes": r["n_boxes"],
                        **{k: r[k] for k in METRIC_FIELDS if k in r},
                    }
                )
        key = (f"B {held}: natural - strict", "overall", "mAP50_95")
        if key in bkey:
            r = bkey[key]
            src_rows.append(
                {
                    "held_out": held,
                    "regime": "natural - strict (paired, same test items)",
                    "model": "",
                    "mAP50_95": r["delta"],
                    "ci_low": r["ci_low"],
                    "ci_high": r["ci_high"],
                }
            )
    _write_csv(
        REPORTS / "source_shift_results.csv",
        src_rows,
        (
            "held_out",
            "regime",
            "model",
            "test_images",
            "test_boxes",
            *METRIC_FIELDS,
            "ci_low",
            "ci_high",
        ),
    )

    payload = {
        "protocol": PROTOCOL,
        "bootstrap": {
            "resamples": BOOTSTRAP,
            "seed": BOOTSTRAP_SEED,
            "unit": "A1 constraint group",
            "interval": "percentile 2.5-97.5",
        },
        "metrics": rows,
        "bootstrap_results": boot,
        "d0_seed_results": seed_rows,
        "probe_control_results": pc_rows,
        "replication_results": rep_rows,
        "source_shift_results": src_rows,
        "validator_check": {n: p.validator for n, p in preds.items()},
    }
    (REPORTS / "final_metrics.json").write_bytes(
        (json.dumps(payload, indent=1, default=float) + "\n").encode("utf-8")
    )
    figures(table, bkey, seed_rows)
    render_reports(table, bkey, environment())


def pts(value: float) -> float:
    """A fraction as percentage points."""
    return 100 * value


def figures(
    table: Mapping[tuple[str, str], Json],
    bkey: Mapping[tuple[str, str, str], Json],
    seed_rows: Sequence[Json],
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {"font.size": 10, "axes.spines.top": False, "axes.spines.right": False, "figure.dpi": 150}
    )
    blue, orange, grey = "#2f6db5", "#d1782c", "#8a8a8a"

    fig, ax = plt.subplots(figsize=(5.2, 3.4))
    for s in (0, 1, 2):
        c0, c1 = (
            table[(f"C0-d0-s{s}", "overall")]["mAP50_95"],
            table[(f"C1-d0-s{s}", "overall")]["mAP50_95"],
        )
        ax.plot([0, 1], [pts(c0), pts(c1)], color=grey, lw=1, zorder=1)
        ax.scatter(
            [0], [pts(c0)], color=blue, zorder=2, label="C0 (mates in training)" if s == 0 else None
        )
        ax.scatter(
            [1], [pts(c1)], color=orange, zorder=2, label="C1 (replacements)" if s == 0 else None
        )
        ax.annotate(f"seed {s}", (1.03, pts(c1)), fontsize=8, va="center")
    ax.set_xticks([0, 1], ["C0", "C1"])
    ax.set_xlim(-0.3, 1.45)
    ax.set_ylabel("mAP50-95 on the D0 common test set (%)")
    ax.set_title(
        "Design 0: the same 407 test images, paired by seed (y axis truncated)", fontsize=9
    )
    ax.legend(frameon=False, fontsize=8, loc="lower left")
    fig.tight_layout()
    fig.savefig(FIGURES / "d0_c0_vs_c1.png")
    plt.close(fig)

    def interval_plot(path: Path, entries: Sequence[tuple[str, str, str]], title: str) -> None:
        fig, ax = plt.subplots(figsize=(7.2, 0.45 * len(entries) + 1.4))
        for k, (_label, comparison, subset) in enumerate(entries):
            r = bkey[(comparison, subset, "mAP50_95")]
            color = {"probe": blue, "control": orange}.get(subset, "black")
            ax.errorbar(
                pts(r["delta"]),
                k,
                xerr=[[pts(r["delta"] - r["ci_low"])], [pts(r["ci_high"] - r["delta"])]],
                fmt="o",
                color=color,
                capsize=3,
            )
        ax.axvline(0, color=grey, lw=1, ls="--")
        ax.set_yticks(range(len(entries)), [e[0] for e in entries])
        ax.invert_yaxis()
        ax.set_xlabel("C0 - C1, mAP50-95 (percentage points, 95% paired bootstrap CI)")
        ax.set_title(title)
        fig.tight_layout()
        fig.savefig(path)
        plt.close(fig)

    interval_plot(
        FIGURES / "d0_delta_by_seed.png",
        [
            *((f"seed {s}", f"D0 seed {s}: C0 - C1", "overall") for s in (0, 1, 2)),
            ("mean of 3 seeds", "D0 mean of seeds 0-2: C0 - C1", "overall"),
        ],
        "Design 0: C0 - C1 on the common test set",
    )
    interval_plot(
        FIGURES / "probe_vs_control_delta.png",
        [
            *((f"seed {s} probe", f"D0 seed {s}: C0 - C1", "probe") for s in (0, 1, 2)),
            ("mean probe", "D0 mean of seeds 0-2: C0 - C1", "probe"),
            *((f"seed {s} control", f"D0 seed {s}: C0 - C1", "control") for s in (0, 1, 2)),
            ("mean control", "D0 mean of seeds 0-2: C0 - C1", "control"),
        ],
        "Design 0: probes (mates in C0 training) and controls",
    )
    interval_plot(
        FIGURES / "d1_d2_replication.png",
        [
            ("D0 mean (3 seeds) overall", "D0 mean of seeds 0-2: C0 - C1", "overall"),
            ("D0 mean (3 seeds) probe", "D0 mean of seeds 0-2: C0 - C1", "probe"),
            ("D0 mean (3 seeds) control", "D0 mean of seeds 0-2: C0 - C1", "control"),
            *((f"D{d} overall", f"D{d} seed 0: C0 - C1", "overall") for d in (1, 2)),
            *((f"D{d} probe", f"D{d} seed 0: C0 - C1", "probe") for d in (1, 2)),
            *((f"D{d} control", f"D{d} seed 0: C0 - C1", "control") for d in (1, 2)),
        ],
        "Replication designs (single seed) next to design 0",
    )

    fig, ax = plt.subplots(figsize=(6.4, 3.4))
    width = 0.25
    for k, src in enumerate(SOURCES):
        bars = [
            (
                "in-distribution test items of this source (A1; A0 for PCB-Defect)",
                (
                    table.get(("A1-s0", f"source:{src}"))
                    or table.get(("A0-s0", f"source:{src}"))
                    or {}
                ).get("mAP50_95"),
                grey,
            ),
            (
                "B-strict (held out)",
                table.get((f"B-strict-{src}-s0", "overall"), {}).get("mAP50_95"),
                blue,
            ),
            (
                "B-natural (held out)",
                table.get((f"B-natural-{src}-s0", "overall"), {}).get("mAP50_95"),
                orange,
            ),
        ]
        for j, (label, value, color) in enumerate(bars):
            if value is not None:
                ax.bar(
                    k + (j - 1) * width,
                    pts(value),
                    width,
                    color=color,
                    label=label if k == 0 else None,
                )
                ax.annotate(
                    f"{pts(value):.1f}",
                    (k + (j - 1) * width, pts(value)),
                    ha="center",
                    va="bottom",
                    fontsize=7,
                )
    ax.set_xticks(range(len(SOURCES)), SOURCES)
    ax.set_ylabel("mAP50-95 (%)")
    ax.set_title("Source held out (B) against in-distribution test items")
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(FIGURES / "source_shift.png")
    plt.close(fig)


# ------------------------------------------------------------------------------------ reports


def environment() -> Json:
    import platform

    import torch
    import ultralytics

    return {
        "python": platform.python_version(),
        "ultralytics": ultralytics.__version__,
        "torch": torch.__version__,
        "numpy": np.__version__,
        "os": platform.platform(),
        "cpu": platform.processor(),
    }


def _pp(value: float) -> str:
    return f"{100 * value:+.2f}"


def _pct(value: float) -> str:
    return f"{100 * value:.2f}"


def _ci(r: Mapping[str, Any]) -> str:
    return f"{_pp(r['ci_low'])} to {_pp(r['ci_high'])}"


def _md(header: Sequence[str], body: Sequence[Sequence[object]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in body]
    return lines


def _reading(subset: str, r: Mapping[str, Any], d0: Mapping[str, Any]) -> str:
    """How a replication row reads against design 0."""
    if subset == "control":
        return "near zero (CI includes 0)" if _excludes_zero(r) == 0 else "moved (CI excludes 0)"
    same = np.sign(r["delta"]) == np.sign(d0["delta"])
    return ("same sign as design 0" if same else "opposite sign") + (
        ", CI excludes 0" if _excludes_zero(r) != 0 else ", CI includes 0"
    )


def _excludes_zero(r: Mapping[str, Any]) -> int:
    """+1 above zero, -1 below zero, 0 when the interval contains zero."""
    if r["ci_low"] > 0:
        return 1
    if r["ci_high"] < 0:
        return -1
    return 0


def render_reports(
    table: Mapping[tuple[str, str], Json],
    bkey: Mapping[tuple[str, str, str], Json],
    env: Mapping[str, Any],
) -> None:
    manifest = json.loads((REPORTS / "final_run_manifest.json").read_text(encoding="utf-8"))
    inventory = json.loads((REPORTS / "evren_run_inventory.json").read_text(encoding="utf-8"))
    valid = sum(1 for r in manifest["runs"] if r["checkpoint_verified"])
    statuses = Counter(j["status"] for j in inventory["jobs"])

    def d(comparison: str, subset: str, metric: str = "mAP50_95") -> Json:
        return dict(bkey[(comparison, subset, metric)])

    mean = d("D0 mean of seeds 0-2: C0 - C1", "overall")
    probe = d("D0 mean of seeds 0-2: C0 - C1", "probe")
    control = d("D0 mean of seeds 0-2: C0 - C1", "control")
    seeds = [d(f"D0 seed {s}: C0 - C1", "overall") for s in (0, 1, 2)]
    seed_probe = [d(f"D0 seed {s}: C0 - C1", "probe") for s in (0, 1, 2)]
    seed_control = [d(f"D0 seed {s}: C0 - C1", "control") for s in (0, 1, 2)]
    did = [d(f"D0 seed {s}: C0 - C1", "probe - control") for s in (0, 1, 2)]
    did_mean = d("D0 mean of seeds 0-2: C0 - C1", "probe - control")
    did_reps = {k: d(f"D{k} seed 0: C0 - C1", "probe - control") for k in (1, 2)}
    sd = float(np.std([r["delta"] for r in seeds], ddof=1))
    reps = {k: d(f"D{k} seed 0: C0 - C1", "overall") for k in (1, 2)}
    reps_probe = {k: d(f"D{k} seed 0: C0 - C1", "probe") for k in (1, 2)}
    reps_control = {k: d(f"D{k} seed 0: C0 - C1", "control") for k in (1, 2)}
    noise = [
        r
        for (c, s, m), r in bkey.items()
        if c.startswith("noise") and s == "overall" and m == "mAP50_95"
    ]
    c1_sd = float(
        np.std([table[(f"C1-d0-s{s}", "overall")]["mAP50_95"] for s in (0, 1, 2)], ddof=1)
    )
    c0_sd = float(
        np.std([table[(f"C0-d0-s{s}", "overall")]["mAP50_95"] for s in (0, 1, 2)], ddof=1)
    )
    floor = max([abs(r["delta"]) for r in noise] + [c0_sd, c1_sd]) if noise else max(c0_sd, c1_sd)
    n_images = table[("C0-d0-s0", "overall")]["n_images"]
    n_probe = table[("C0-d0-s0", "probe")]["n_images"]
    n_control = table[("C0-d0-s0", "control")]["n_images"]

    # --------------------------------------------------------------- evaluation_protocol.md
    protocol = [
        "# M7 evaluation protocol",
        "",
        "Generated by `scripts/m7_evaluate.py`. Nothing was trained locally: every model is the "
        "best.pt that EVREN trained, downloaded through EVREN's model-version download API by "
        "`scripts/m7_checkpoints.py` and identified by its EVREN job and model version "
        "(`final_run_manifest.json`, `checkpoint_manifest.csv`, SHA-256 checked before use).",
        "",
        "## Environment",
        "",
        *_md(["component", "version"], [[k, f"`{v}`"] for k, v in env.items()]),
        "",
        "Ultralytics 8.3.0 is the version recorded in every checkpoint. It runs in a separate "
        "environment (AGPL-3.0, never a dependency of this project) with a CPU build of torch; "
        "usage analytics (`sync`) are switched off.",
        "",
        "## Inference and matching",
        "",
        *_md(
            ["setting", "value"],
            [[f"`{k}`", f"`{v}`"] for k, v in PROTOCOL.items()],
        ),
        "",
        "- Ultralytics' `DetectionValidator`, unchanged, run on the test split of each model's "
        "package; a subclass only records every image's detections and true-positive flags. "
        "Matching is Ultralytics' `match_predictions` at IoU 0.50, 0.55, ..., 0.95 (class-aware).",
        "- Metrics are recomputed from the recorded detections with Ultralytics' `ap_per_class` "
        "(101-point interpolated AP). For every model the recomputation equals the validator's "
        "own mAP50-95 and mAP50 to 1e-9. mAP50-95 averages AP over the ten IoU thresholds and the "
        "classes present in the evaluated items; precision and recall are the class means at the "
        "confidence that maximises the mean F1; F1 is their harmonic mean.",
        "- The same implementation and settings evaluate every model; models of one comparison see "
        "the same images in the same order.",
        "",
        "## Test populations",
        "",
        "- C0 and C1 of a design are evaluated on the test split of the C0 package of that "
        "design; the script checks that the C1 package's test labels are byte-identical. Design 0: "
        f"{n_images} images, {n_probe} probes and {n_control} controls.",
        "- Probe and control membership comes from `manifests/experiments/v0.1/C-design<d>-roles.csv` "
        "(M5.5); the script checks that probes and controls are exactly the test set.",
        "- A0 and A1 use their own test splits; a B-strict and a B-natural model of one held-out "
        "source share the same test split (checked). Every package ZIP is checked against the "
        "SHA-256 recorded in M5.5 (`artifacts/m5_5/readiness.json`).",
        "",
        "## Uncertainty",
        "",
        f"- Paired bootstrap: {BOOTSTRAP} resamples, NumPy `default_rng([{BOOTSTRAP_SEED}, crc32(population/subset)])`, "
        "percentile 95% intervals. Each resample draws whole A1 constraint groups "
        "(`constraint_group` in `items.parquet`) with replacement from the evaluated items; both "
        "models of a comparison are scored on the same resample and their difference is taken.",
        "- Why groups: items of one constraint group are linked (same production batch, design "
        "family, crop parent or visual similarity component) and are not independent test "
        "evidence; the M7 plan froze the A1 constraint group as the resampling unit.",
        "- The three-seed mean of design 0 is recomputed on every resample with the same resample "
        "for the three seeds, so its interval reflects test-set sampling; the variation between "
        "training seeds is reported separately as their standard deviation.",
        "",
        "## Reproduce",
        "",
        "```",
        "python scripts/evren_inventory.py --verify-items --checkpoints <data>/models/m7  # project env",
        "python scripts/m7_checkpoints.py                                                # project env",
        "<m7-eval env>/python scripts/m7_evaluate.py --data-dir <data>                   # Ultralytics 8.3.0",
        "```",
        "",
        "Per-image detections are stored in `<data>/m7/eval/` (not committed).",
        "",
    ]
    (REPORTS / "evaluation_protocol.md").write_bytes("\n".join(protocol).encode("utf-8"))

    # --------------------------------------------------------------------- final_results.md
    lines = [
        "# M7 results",
        "",
        "Generated by `scripts/m7_evaluate.py` under one local protocol "
        "([evaluation_protocol.md](evaluation_protocol.md)). EVREN's dashboard scores are not "
        "used. Differences are in mAP50-95 percentage points (pp), C0 minus C1 unless stated.",
        "",
        "**Human validation: NOT PERFORMED.** The groups behind probes and controls are "
        "machine-detected visual similarity components and source metadata; no person checked "
        "whether grouped images are duplicates.",
        "",
        "## Run state",
        "",
        f"- EVREN jobs: {len(inventory['jobs'])} ({', '.join(f'{k} {v}' for k, v in sorted(statuses.items()))}); "
        f"planned runs with a valid, verified checkpoint: **{valid} of {len(manifest['runs'])}** "
        "([final_run_manifest.csv](final_run_manifest.csv)).",
        f"- One effective training configuration for every checkpoint "
        f"({manifest['distinct_effective_configs']} distinct effective-configuration hash).",
        "",
        f"## Primary experiment: design 0 ({n_images} common test images: {n_probe} probes, {n_control} controls)",
        "",
        *_md(
            [
                "seed",
                "C0 mAP50-95",
                "C1 mAP50-95",
                "C0 - C1 (pp)",
                "95% CI (pp)",
                "C0 - C1 mAP50 (pp)",
                "C0 - C1 F1 (pp)",
            ],
            [
                [
                    s,
                    _pct(table[(f"C0-d0-s{s}", "overall")]["mAP50_95"]),
                    _pct(table[(f"C1-d0-s{s}", "overall")]["mAP50_95"]),
                    f"**{_pp(seeds[s]['delta'])}**",
                    _ci(seeds[s]),
                    _pp(
                        table[(f"C0-d0-s{s}", "overall")]["mAP50"]
                        - table[(f"C1-d0-s{s}", "overall")]["mAP50"]
                    ),
                    _pp(
                        table[(f"C0-d0-s{s}", "overall")]["F1"]
                        - table[(f"C1-d0-s{s}", "overall")]["F1"]
                    ),
                ]
                for s in (0, 1, 2)
            ]
            + [
                [
                    "mean of 3",
                    "",
                    "",
                    f"**{_pp(mean['delta'])}**",
                    _ci(mean),
                    _pp(d("D0 mean of seeds 0-2: C0 - C1", "overall", "mAP50")["delta"]),
                    "",
                ]
            ],
        ),
        "",
        f"Standard deviation of the three seed differences: {100 * sd:.2f} pp.",
        "",
        "## Probes and controls (design 0)",
        "",
        *_md(
            [
                "seed",
                "probe C0 - C1 (pp)",
                "probe 95% CI",
                "control C0 - C1 (pp)",
                "control 95% CI",
                "probe - control (pp)",
                "95% CI",
            ],
            [
                [
                    s,
                    _pp(seed_probe[s]["delta"]),
                    _ci(seed_probe[s]),
                    _pp(seed_control[s]["delta"]),
                    _ci(seed_control[s]),
                    _pp(did[s]["delta"]),
                    _ci(did[s]),
                ]
                for s in (0, 1, 2)
            ]
            + [
                [
                    "mean of 3",
                    f"**{_pp(probe['delta'])}**",
                    _ci(probe),
                    f"**{_pp(control['delta'])}**",
                    _ci(control),
                    f"**{_pp(did_mean['delta'])}**",
                    _ci(did_mean),
                ]
            ],
        ),
        "",
        "Probes are test items whose group-mates C0 trains on; controls are whole groups that "
        "neither condition trains on. The C0 - C1 difference is computed within each subset; the "
        "last columns compare the two differences (probe - control, a difference in differences; "
        "probes and controls hold different groups and are resampled independently). Their "
        "levels are not compared: the two subsets differ in composition and difficulty.",
        "",
        "## Per-class AP50-95, design 0 (mean of the three seeds)",
        "",
        *_md(
            ["class", "C0", "C1", "C0 - C1 (pp)"],
            [
                [
                    c,
                    _pct(
                        float(
                            np.mean(
                                [
                                    table[(f"C0-d0-s{s}", "overall")].get(
                                        f"AP50_95_{c}", float("nan")
                                    )
                                    for s in (0, 1, 2)
                                ]
                            )
                        )
                    ),
                    _pct(
                        float(
                            np.mean(
                                [
                                    table[(f"C1-d0-s{s}", "overall")].get(
                                        f"AP50_95_{c}", float("nan")
                                    )
                                    for s in (0, 1, 2)
                                ]
                            )
                        )
                    ),
                    _pp(
                        float(
                            np.mean(
                                [
                                    table[(f"C0-d0-s{s}", "overall")].get(
                                        f"AP50_95_{c}", float("nan")
                                    )
                                    - table[(f"C1-d0-s{s}", "overall")].get(
                                        f"AP50_95_{c}", float("nan")
                                    )
                                    for s in (0, 1, 2)
                                ]
                            )
                        )
                    ),
                ]
                for c in CLASSES
            ],
        ),
        "",
        "## Replication designs (one seed each)",
        "",
        *_md(
            [
                "design",
                "subset",
                "C0 - C1 mAP50-95 (pp)",
                "95% CI",
                "C0 - C1 mAP50 (pp)",
                "reading",
            ],
            [
                [
                    k,
                    subset,
                    _pp(r["delta"]),
                    _ci(r),
                    _pp(d(f"D{k} seed 0: C0 - C1", subset, "mAP50")["delta"]),
                    _reading(subset, r, d("D0 mean of seeds 0-2: C0 - C1", subset)),
                ]
                for k in (1, 2)
                for subset, r in (
                    ("overall", reps[k]),
                    ("probe", reps_probe[k]),
                    ("control", reps_control[k]),
                    ("probe - control", did_reps[k]),
                )
            ],
        ),
        "",
        "Designs 1 and 2 are other seeded draws of probes, controls and replacements, trained "
        "once each: they test whether the sign reproduces, and are not averaged with the three "
        "seeds of design 0.",
        "",
        "## Training-noise baseline",
        "",
        *_md(
            [
                "pair (identical dataset version, seed and configuration)",
                "test population",
                "difference mAP50-95 (pp)",
                "95% CI",
            ],
            [
                [r["comparison"].removeprefix("noise "), r["population"], _pp(r["delta"]), _ci(r)]
                for r in noise
            ],
        ),
        "",
        f"Between-seed standard deviation of test mAP50-95 on design 0: C0 {100 * c0_sd:.2f} pp, C1 "
        f"{100 * c1_sd:.2f} pp. Empirical noise floor used below (largest of these): "
        f"{100 * floor:.2f} pp.",
        "",
        "## DESCRIPTIVE SPLIT COMPARISON: A0 and A1",
        "",
        *_md(
            [
                "model",
                "test items",
                "mAP50-95",
                "mAP50",
                "DsPCBSD+ items",
                "PCB-Defect items",
                "PCB-IND items",
            ],
            [
                [
                    m,
                    table[(m, "overall")]["n_images"],
                    _pct(table[(m, "overall")]["mAP50_95"]),
                    _pct(table[(m, "overall")]["mAP50"]),
                    *(
                        f"{_pct(table[(m, f'source:{s}')]['mAP50_95'])} ({table[(m, f'source:{s}')]['n_images']})"
                        if (m, f"source:{s}") in table
                        else "none"
                        for s in SOURCES
                    ),
                ]
                for m in ("A0-s0", "A1-s0")
            ],
        ),
        "",
        "A0 and A1 are evaluated on different test populations (A1 has no PCB-Defect test item); "
        "their difference is descriptive and is **not** a leakage effect.",
        "",
        "## Source held out (B): source and domain shift",
        "",
        *_md(
            [
                "held-out source",
                "test items",
                "B-strict mAP50-95",
                "B-natural mAP50-95",
                "natural - strict (pp, same items)",
                "95% CI",
                "A1 items of this source (in-distribution, other items)",
            ],
            [
                [
                    s,
                    table[(f"B-strict-{s}-s0", "overall")]["n_images"],
                    _pct(table[(f"B-strict-{s}-s0", "overall")]["mAP50_95"]),
                    _pct(table[(f"B-natural-{s}-s0", "overall")]["mAP50_95"])
                    if (f"B-natural-{s}-s0", "overall") in table
                    else "= strict",
                    _pp(d(f"B {s}: natural - strict", "overall")["delta"])
                    if (f"B {s}: natural - strict", "overall", "mAP50_95") in bkey
                    else "-",
                    _ci(d(f"B {s}: natural - strict", "overall"))
                    if (f"B {s}: natural - strict", "overall", "mAP50_95") in bkey
                    else "-",
                    _pct(table[("A1-s0", f"source:{s}")]["mAP50_95"])
                    if ("A1-s0", f"source:{s}") in table
                    else "none (no A1 test item)",
                ]
                for s in SOURCES
            ],
        ),
        "",
        "The same evaluator scores A0's PCB-Defect test items at "
        + (
            _pct(table[("A0-s0", "source:pcb-defect")]["mAP50_95"])
            if ("A0-s0", "source:pcb-defect") in table
            else "-"
        )
        + " mAP50-95, so the near-zero score of the model that never saw PCB-Defect is a "
        "transfer failure, not an evaluation artefact.",
        "",
        "B measures how a model transfers to a source it never saw; the source probe of M5.5 "
        "showed that sources are trivially distinguishable, so these numbers describe source and "
        "domain shift, not leakage, and are not compared with C0/C1.",
        "",
    ]
    lines += verdict_section(
        table,
        bkey,
        {
            "mean": mean,
            "probe": probe,
            "control": control,
            "did": did_mean,
            "seeds": seeds,
            "seed_probe": seed_probe,
            "seed_control": seed_control,
            "reps": reps,
            "reps_probe": reps_probe,
            "reps_control": reps_control,
            "did_reps": did_reps,
        },
        sd,
        floor,
    )
    (REPORTS / "final_results.md").write_bytes("\n".join(lines).encode("utf-8"))


def verdict_section(
    table: Mapping[tuple[str, str], Json],
    bkey: Mapping[tuple[str, str, str], Json],
    r: Mapping[str, Any],
    sd: float,
    floor: float,
) -> list[str]:
    """The fifteen answers. The rules were written before the design-0 numbers were computed;
    the strength rule was tightened after the first rendering (see the rule note)."""
    mean, probe, control, did = r["mean"], r["probe"], r["control"], r["did"]
    seeds, seed_probe, seed_control = r["seeds"], r["seed_probe"], r["seed_control"]
    reps, reps_probe, reps_control, did_reps = (
        r["reps"],
        r["reps_probe"],
        r["reps_control"],
        r["did_reps"],
    )
    zero = {1: "excludes zero", -1: "excludes zero (below)", 0: "includes zero"}
    m_sig, p_sig, c_sig, d_sig = (_excludes_zero(x) for x in (mean, probe, control, did))
    control_small = c_sig == 0 and abs(control["delta"]) <= floor
    positive = sum(1 for x in seeds if x["delta"] > 0)
    probe_pos = sum(1 for x in seed_probe if x["delta"] > 0)
    rep_probe_up = {k: reps_probe[k]["delta"] > 0 for k in (1, 2)}
    rep_probe_sig = {k: _excludes_zero(reps_probe[k]) == 1 for k in (1, 2)}
    rep_control_flat = {k: _excludes_zero(reps_control[k]) == 0 for k in (1, 2)}
    beyond_noise = abs(mean["delta"]) > floor
    ratio = abs(mean["delta"]) / floor if floor else float("inf")
    probe_ratio = abs(probe["delta"]) / floor if floor else float("inf")

    if (
        p_sig == 1
        and control_small
        and d_sig == 1
        and probe_pos == 3
        and all(rep_probe_up.values())
    ):
        support = "yes"
        strong = (
            m_sig == 1
            and beyond_noise
            and all(rep_control_flat.values())
            and all(rep_probe_sig.values())
        )
        strength = "strong within this setting" if strong else "moderate"
    elif probe["delta"] > 0 and (p_sig == 1 or probe_pos >= 2):
        support, strength = "partly", "weak"
    elif p_sig == -1:
        support, strength = "no (contrary)", "none"
    else:
        support, strength = "no", "none"
    clean = [0] + [k for k in (1, 2) if rep_control_flat[k] and _excludes_zero(did_reps[k]) == 1]
    unclean = [k for k in (1, 2) if not rep_control_flat[k]]

    a: list[str] = []
    a.append(
        ("Yes" if m_sig == 1 else "No" if m_sig == -1 else "Not distinguishably")
        + f": C0 scored higher on {positive} of 3 seeds; the three-seed mean difference is "
        f"{_pp(mean['delta'])} pp (95% CI {_ci(mean)}; the interval {zero[m_sig]}). Each single "
        "seed's interval includes zero."
        if all(_excludes_zero(x) == 0 for x in seeds)
        else ("Yes" if m_sig == 1 else "No" if m_sig == -1 else "Not distinguishably")
        + f": C0 scored higher on {positive} of 3 seeds; the three-seed mean difference is "
        f"{_pp(mean['delta'])} pp (95% CI {_ci(mean)}; the interval {zero[m_sig]})."
    )
    a.append(
        "; ".join(f"seed {k}: {_pp(x['delta'])} pp (CI {_ci(x)})" for k, x in enumerate(seeds))
        + "."
    )
    a.append(f"{_pp(mean['delta'])} pp; between-seed standard deviation {100 * sd:.2f} pp.")
    a.append(
        f"{_ci(mean)} pp for the three-seed mean: paired bootstrap over A1 constraint groups "
        f"({BOOTSTRAP} resamples, RNG seed {BOOTSTRAP_SEED}, the same resamples for the three "
        "seeds). It reflects the sampling of the test set, not the variation between training seeds."
    )
    a.append(
        f"The probes carry the difference: mean {_pp(probe['delta'])} pp (CI {_ci(probe)}; the "
        f"interval {zero[p_sig]}); "
        + ", ".join(f"seed {k} {_pp(x['delta'])}" for k, x in enumerate(seed_probe))
        + f"; C0 higher on {probe_pos} of 3 seeds."
    )
    a.append(
        f"Controls: mean {_pp(control['delta'])} pp (CI {_ci(control)}; the interval "
        f"{zero[c_sig]}); "
        + ", ".join(f"seed {k} {_pp(x['delta'])}" for k, x in enumerate(seed_control))
        + f". Probe minus control: {_pp(did['delta'])} pp (CI {_ci(did)}; the interval {zero[d_sig]})."
    )
    for k in (1, 2):
        a.append(
            ("Yes" if np.sign(reps[k]["delta"]) == np.sign(mean["delta"]) else "No")
            + f" for the overall score: {_pp(reps[k]['delta'])} pp (CI {_ci(reps[k])}); probes "
            f"{_pp(reps_probe[k]['delta'])} pp (CI {_ci(reps_probe[k])}); controls "
            f"{_pp(reps_control[k]['delta'])} pp (CI {_ci(reps_control[k])}"
            + (
                "), so the gain sits on the probes as in design 0"
                if rep_control_flat[k]
                else "), which also moved: in this design the gain is not confined to the probes"
            )
            + f"; probe minus control {_pp(did_reps[k]['delta'])} pp (CI {_ci(did_reps[k])}). One seed."
        )
    a.append(
        ("Yes, modestly" if beyond_noise else "No")
        + f": the three-seed mean ({_pp(mean['delta'])} pp) is {ratio:.1f} times the empirical "
        f"noise floor ({100 * floor:.2f} pp: the largest test difference between identically "
        "configured replicates or the between-seed SD). Single-seed overall differences ("
        + ", ".join(_pp(x["delta"]) for x in seeds)
        + f") are of the same order as that floor. The probe difference ({_pp(probe['delta'])} pp) "
        f"is {probe_ratio:.1f} times the floor."
    )
    a.append(
        {
            "yes": "Yes, for this benchmark and model, with a qualification: in design 0 (three seeds)"
            + (" and design " + " and ".join(str(k) for k in clean[1:]) if clean[1:] else "")
            + " the gain is concentrated on the test images whose machine-defined group-mates were "
            "in training, while unexposed controls did not move measurably"
            + (
                "; in design " + " and ".join(str(k) for k in unclean) + " (one seed) the controls "
                "improved as well, so not all of the C0 - C1 gain there is explained by exposure."
                if unclean
                else "."
            ),
            "partly": "Partly: the direction matches the hypothesis on the probes, but the evidence "
            "does not separate the effect from noise convincingly.",
            "no (contrary)": "No: the probes scored lower with their group-mates in training, "
            "contrary to the hypothesis.",
            "no": "No: the data show no measurable advantage from training on group-mates of test images.",
        }[support]
    )
    a.append(
        {
            "strong within this setting": "Strong within this setting (one architecture, one "
            "benchmark): the probe effect is positive in every seed and design with intervals above "
            "zero, the controls stay near zero everywhere, and the effect exceeds the noise floor.",
            "moderate": "Moderate. For: the probe effect is positive in all three seeds and both "
            "replication designs, its three-seed interval excludes zero, the probe - control "
            "contrast excludes zero, and the controls of design 0 stay near zero. Against: the "
            "overall effect is small (about two points) and of the order of training noise for a "
            "single seed"
            + (
                ", and the controls of design "
                + " and ".join(str(k) for k in unclean)
                + " moved too"
                if unclean
                else ""
            )
            + ".",
            "weak": "Weak: the direction is suggestive but the intervals or the replication do not "
            "support a firm statement.",
            "none": "None for the hypothesis as stated.",
        }[strength]
    )
    a.append(
        "The groups are machine-detected and not human-validated, so the exposure is to "
        "machine-defined group-mates, not to verified duplicates; one architecture (YOLO11n), "
        "one domain (PCB defects) and one release; three training seeds for design 0 and one each "
        "for designs 1 and 2; EVREN training is not bit-for-bit reproducible; probes and controls "
        "are small subsets of different composition; the bootstrap covers test sampling, not "
        "training variation; the runs used a cosine learning-rate schedule and label smoothing "
        "0.1, which the plan did not specify (identical in every run); PCB-Defect contributes "
        "few probes and controls and no validation item."
    )
    b_rows = []
    for src in SOURCES:
        strict = table.get((f"B-strict-{src}-s0", "overall"))
        ref = table.get(("A1-s0", f"source:{src}")) or table.get(("A0-s0", f"source:{src}"))
        ref_name = "A1" if ("A1-s0", f"source:{src}") in table else "A0"
        if strict:
            text = f"{src} held out: {_pct(strict['mAP50_95'])}"
            if ref:
                text += f" (against {_pct(ref['mAP50_95'])} on {ref_name}'s in-distribution items of that source)"
            key = (f"B {src}: natural - strict", "overall", "mAP50_95")
            if key in bkey:
                text += f"; natural - strict {_pp(bkey[key]['delta'])} pp (CI {_ci(bkey[key])})"
            b_rows.append(text)
    a.append(
        "A large source shift: "
        + "; ".join(b_rows)
        + ". Keeping the machine-similar cross-source items (B-natural) did not raise held-out "
        "scores. These measure source and domain shift, not leakage, and they dwarf the C0 - C1 "
        "effect."
    )
    if support == "yes":
        head = (
            f"In a controlled YOLO11n experiment, training on machine-detected group-mates of test "
            f"images raised mAP50-95 on those images by {_pp(probe['delta'])} pp (95% CI "
            f"{_ci(probe)}, three seeds) while unexposed controls did not change "
            f"({_pp(control['delta'])} pp): group leakage makes this PCB benchmark measurably but "
            "modestly optimistic, far less than the loss when a source is held out."
        )
    elif support == "partly":
        head = (
            f"A controlled test found at most a small, uncertain benefit from training on group-mates "
            f"of test images ({_pp(probe['delta'])} pp on probes, 95% CI {_ci(probe)})."
        )
    else:
        head = (
            f"A controlled test found no measurable optimism from training on machine-detected "
            f"group-mates of test images ({_pp(probe['delta'])} pp on probes, 95% CI {_ci(probe)})."
        )
    a.append(head)
    half_width = (probe["ci_high"] - probe["ci_low"]) / 2
    if support == "yes":
        need = (
            "Not for the claim as tested: the planned matrix is complete (three seeds on design 0, "
            "one each on designs 1 and 2)."
            + (
                " Optional: two more seeds of design "
                + " and ".join(str(k) for k in unclean)
                + " would show whether its control gain is training noise."
                if unclean
                else ""
            )
            + " A human review of the groups would strengthen the interpretation more than more training."
        )
    elif support == "partly" or half_width > max(floor, 0.01):
        need = (
            f"Possibly: the probe interval (half-width {100 * half_width:.2f} pp) is wide relative "
            "to the noise floor; more seeds of design 0 under the same configuration would decide."
        )
    else:
        need = (
            f"No: the matrix is complete and the probe interval (half-width {100 * half_width:.2f} "
            "pp) already rules out an effect much larger than that."
        )
    a.append(need)
    questions = (
        "Did C0 outperform C1 on the common D0 test population?",
        "By how many mAP50-95 points on each seed?",
        "What was the 3-seed mean delta?",
        "What is the paired 95% confidence interval?",
        "What happened on probe examples?",
        "What happened on controls?",
        "Did D1 reproduce the direction?",
        "Did D2 reproduce the direction?",
        "Is the observed effect larger than empirical training noise?",
        "Does the evidence support the claim that similarity/group leakage can make benchmark performance overly optimistic?",
        "How strong is that evidence?",
        "What limitations prevent a stronger claim?",
        "What did source-held-out B experiments show?",
        "What should go into the paper/technical report headline?",
        "Is another training run scientifically necessary?",
    )
    out = [
        "## Scientific verdict",
        "",
        "Rule note: the support and strength rules are code in `scripts/m7_evaluate.py`, written "
        "before the design-0 numbers were computed. The first rendering of this report checked "
        "neither the controls of the replication designs nor the probe - control contrast; both "
        "checks were added afterwards. They can only lower the rating, and they did (from strong "
        "to moderate).",
        "",
    ]
    for k, (q, ans) in enumerate(zip(questions, a, strict=True), start=1):
        out += [f"**{k}. {q}**", "", ans, ""]
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--data-dir", type=Path, default=Path(os.environ.get("OPENINSPECT_DATA_DIR", ""))
    )
    parser.add_argument("--stage", choices=("infer", "analyze", "all"), default="all")
    parser.add_argument("--only", nargs="*", default=None, help="models to infer (default: all)")
    args = parser.parse_args(argv)
    if not args.data_dir.is_dir():
        print("pass --data-dir or set OPENINSPECT_DATA_DIR", file=sys.stderr)
        return 2
    steps: dict[str, Callable[[], None]] = {
        "infer": lambda: run_inference(args.data_dir, args.only),
        "analyze": lambda: analyze(args.data_dir),
    }
    for stage in ("infer", "analyze"):
        if args.stage in (stage, "all"):
            steps[stage]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
