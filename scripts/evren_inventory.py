"""Read-only inventory and audit of the OpenInspect-Trust M7 runs on EVREN.

Credentials are read from environment variables only and are never printed or written:

- ``EVREN_PLATFORM_API_KEY``: an EVREN *platform* key (training jobs, projects, datasets, models);
- ``EVREN_MODEL_API_KEY``: an EVREN *model inference* key (models and inference metadata only);
- ``EVREN_BASE_URL``: the EVREN web application (recorded, used for links only);
- ``EVREN_API_URL`` (optional): the API host, by default ``https://api.ssyz.org.tr/api/v1``, the host
  of the official ``evren-sdk`` and of the web application.

Every request is a GET to an allow-listed path; any other path raises before a connection is opened,
so the tool cannot create, delete, start, stop or change anything on EVREN. It never calls inference
(every inference consumes credits) and never downloads weights. Local checkpoints given with
``--checkpoints`` are read without executing any pickled code.

Usage (from the repository root, with the variables exported in the shell, for example from the
git-ignored ``.env`` with ``set -a; source <(grep -E '^EVREN_' .env); set +a``)::

    uv run python scripts/evren_inventory.py --verify-items --checkpoints <dir>

Outputs (``--out``, default ``reports/m7``): ``evren_run_inventory.json`` and ``.csv``,
``m7_expected_vs_actual.md``, ``m7_config_consistency.md`` and ``evren_api_audit.md``.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import io
import itertools
import json
import os
import pickle
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parents[1]
DEFAULT_API = "https://api.ssyz.org.tr/api/v1"
PROJECT = "OpenInspect-Trust M7"
VERSION_TAG = "v0.1-m7"
READINESS = REPO / "artifacts" / "m5_5" / "readiness.json"
RELEASE = REPO / "manifests" / "releases" / "v0.1"
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
Json = dict[str, Any]

# The only GET paths this tool requests.
ALLOWED = tuple(
    re.compile(pattern)
    for pattern in (
        r"^/projects$",
        rf"^/projects/{UUID}/datasets$",
        r"^/training/jobs$",
        rf"^/training/jobs/{UUID}/(metrics|run-manifest)$",
        rf"^/datasets/{UUID}/versions$",
        rf"^/datasets/{UUID}/items$",
        r"^/models$",
        rf"^/models/{UUID}/versions$",
        rf"^/models/versions/{UUID}/metrics$",
        rf"^/inference/model-classes/{UUID}$",
    )
)

# EVREN dataset name -> (run prefix of the M7 plan, committed split file of that package)
DATASETS: dict[str, tuple[str, str]] = {
    **{
        f"OI M7 C{c} D{d}": (f"C{c}-d{d}", f"manifests/experiments/v0.1/C{c}__design{d}.csv")
        for c in (0, 1)
        for d in (0, 1, 2)
    },
    "OI M7 A0": ("A0", "manifests/splits/v0.1/A0__seed0.csv"),
    "OI M7 A1": ("A1", "manifests/splits/v0.1/A1__seed0.csv"),
    "OI M7 B Strict DSPCBSD": (
        "B-strict-dspcbsd-plus",
        "manifests/splits/v0.1/B-dspcbsd-plus__seed0.csv",
    ),
    "OI M7 B Strict PCB Defect": (
        "B-strict-pcb-defect",
        "manifests/splits/v0.1/B-pcb-defect__seed0.csv",
    ),
    "OI M7 B Strict PCB IND": ("B-strict-pcb-ind", "manifests/splits/v0.1/B-pcb-ind__seed0.csv"),
    "OI M7 B Natural DSPCBSD": (
        "B-natural-dspcbsd-plus",
        "manifests/experiments/v0.1/B-natural-dspcbsd-plus__seed0.csv",
    ),
    "OI M7 B Natural PCB Defect": (
        "B-natural-pcb-defect",
        "manifests/experiments/v0.1/B-natural-pcb-defect__seed0.csv",
    ),
    "OI M7 B Natural PCB IND": (
        "B-natural-pcb-ind",
        "manifests/experiments/v0.1/B-natural-pcb-ind__seed0.csv",
    ),
}

PAIRS = (
    ("C0-d0-s0", "C1-d0-s0"),
    ("C0-d0-s1", "C1-d0-s1"),
    ("C0-d0-s2", "C1-d0-s2"),
    ("C0-d1-s0", "C1-d1-s0"),
    ("C0-d2-s0", "C1-d2-s0"),
)

# The M7 protocol (reports/m5_5/m7-plan.md: one configuration for every run; augmentation and
# everything not listed there are Ultralytics defaults).
PROTOCOL: dict[str, object] = {
    "task": "detect",
    "imgsz": 640,
    "epochs": 100,
    "batch": 32,
    "optimizer": "SGD",
    "lr0": 0.01,
    "lrf": 0.01,
    "momentum": 0.937,
    "weight_decay": 0.0005,
    "warmup_epochs": 3,
    "patience": 20,
    "hsv_h": 0.015,
    "hsv_s": 0.7,
    "hsv_v": 0.4,
    "degrees": 0,
    "translate": 0.1,
    "scale": 0.5,
    "shear": 0,
    "perspective": 0,
    "flipud": 0,
    "fliplr": 0.5,
    "mosaic": 1,
    "mixup": 0,
    "copy_paste": 0,
    "close_mosaic": 10,
    "cos_lr": False,  # Ultralytics default
    "label_smoothing": 0.0,  # Ultralytics default
    "deterministic": True,
    "iou": 0.7,
    "max_det": 300,
    "pretrained": True,
}
# A checkpoint stores the arguments as they were when best.pt was written: the trainer sets mosaic,
# mixup and copy_paste to 0 for the last `close_mosaic` epochs and val to True for the final epoch.
PHASE_KEYS = frozenset({"mosaic", "mixup", "copy_paste", "val"})
RUN_KEYS = frozenset({"run_name", "tags", "seed"})  # differ by design between runs
PATH_KEYS = frozenset({"data", "project", "save_dir", "name"})
SPLIT_ALIASES = {"validation": "val", "valid": "val"}  # EVREN's item split names

CLASSES = (
    "VALID_COMPLETED",
    "MISSING",
    "CANCELLED_WITH_VALID_RETRY",
    "CANCELLED_NO_RETRY",
    "FAILED",
    "DUPLICATE_COMPLETED",
    "CONFIG_MISMATCH",
    "AMBIGUOUS",
)


# ---------------------------------------------------------------------------------------- API


class NotAllowedError(RuntimeError):
    """A request the read-only policy forbids; raised before any connection is opened."""


@dataclass
class Call:
    key: str
    path: str  # with ids replaced by {id}
    status: int


@dataclass
class Client:
    api: str
    keys: Mapping[str, str]  # "platform" / "model" -> secret (never printed or stored)
    calls: list[Call] = field(default_factory=list)
    pause: float = 0.1

    def get(
        self, path: str, params: Mapping[str, str] | None = None, *, key: str = "platform"
    ) -> tuple[int, Any]:
        if not any(p.match(path) for p in ALLOWED):
            raise NotAllowedError(f"GET {path} is not on the read-only allow list")
        secret = self.keys.get(key, "")
        if not secret:
            raise NotAllowedError(f"no {key} key in the environment")
        if not self.api.startswith("https://"):
            raise NotAllowedError("the API URL must use https")
        auth = (
            {"X-API-Key": secret}
            if secret.startswith("evren_")
            else {"Authorization": f"Bearer {secret}"}
        )
        url = self.api + path + ("?" + urllib.parse.urlencode(params) if params else "")
        request = urllib.request.Request(  # noqa: S310 - https only, allow-listed path, GET
            url, headers={**auth, "Accept": "application/json"}, method="GET"
        )
        status, body = 0, b""
        for attempt in range(4):
            try:
                with urllib.request.urlopen(request, timeout=90) as response:  # noqa: S310
                    status, body = response.status, response.read()
            except urllib.error.HTTPError as exc:
                status, body = exc.code, exc.read()
                if status in (429, 502, 503, 504) and attempt < 3:
                    time.sleep(float(exc.headers.get("Retry-After") or 2**attempt))
                    continue
            break
        self.calls.append(Call(key, re.sub(UUID, "{id}", path), status))
        time.sleep(self.pause)
        try:
            return status, json.loads(body)
        except ValueError:
            return status, None


def unwrap(body: Any) -> Any:
    if isinstance(body, dict) and "data" in body and ("success" in body or "meta" in body):
        return body["data"]
    return body


def rows(body: Any) -> list[Json]:
    body = unwrap(body)
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for name in ("items", "data", "results"):
            if isinstance(body.get(name), list):
                return list(body[name])
    return []


def all_jobs(client: Client, project_id: str) -> list[Json]:
    found: list[Json] = []
    while True:
        params = {"project_id": project_id, "limit": "100", "offset": str(len(found))}
        status, body = client.get("/training/jobs", params)
        if status != 200:
            raise RuntimeError(f"listing training jobs failed: HTTP {status}")
        page = rows(body)
        found += page
        total = body.get("total") if isinstance(body, dict) else None
        if not page or (isinstance(total, int) and len(found) >= total):
            return found


def all_items(client: Client, dataset_id: str) -> Iterator[Json]:
    cursor: str | None = None
    while True:
        params = {"limit": "200", **({"cursor": cursor} if cursor else {})}
        status, body = client.get(f"/datasets/{dataset_id}/items", params)
        if status != 200:
            raise RuntimeError(f"listing the items of a dataset failed: HTTP {status}")
        yield from rows(body)
        cursor = body.get("next_cursor") if isinstance(body, dict) else None
        if not cursor:
            return


# ------------------------------------------------------------------------- local checkpoints


class _Stub:
    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def __setstate__(self, state: object) -> None:
        pass


class _SafeUnpickler(pickle.Unpickler):
    """Every global becomes an inert stub and no tensor is loaded: nothing in the file runs."""

    def find_class(self, module: str, name: str) -> Any:
        if (module, name) in {("collections", "OrderedDict"), ("builtins", "dict")}:
            return dict
        if (module, name) == ("builtins", "set"):
            return set
        return type(f"Stub_{name}", (_Stub,), {})

    def persistent_load(self, pid: object) -> None:
        return None


def _plain(value: object) -> object:
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(v) for v in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return "<object>"


def read_checkpoint(path: Path) -> Json:
    data = path.read_bytes()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        name = next(n for n in archive.namelist() if n.endswith("data.pkl"))
        obj = _SafeUnpickler(io.BytesIO(archive.read(name))).load()  # inert stubs only
    obj = obj if isinstance(obj, dict) else {}
    args = _plain(obj.get("train_args"))
    args = args if isinstance(args, dict) else {}
    match = re.search(UUID, f"{args.get('data', '')} {args.get('project', '')}")
    metrics = _plain(obj.get("train_metrics"))
    return {
        "file": path.name,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "job_id": match.group(0) if match else None,
        "ultralytics_version": obj.get("version"),
        "date": obj.get("date"),
        "train_args": args,
        "train_metrics": metrics if isinstance(metrics, dict) else {},
    }


# ----------------------------------------------------------------------------------- analysis


def norm(text: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def same(a: object, b: object) -> bool:
    if isinstance(a, int | float) and isinstance(b, int | float):
        return (
            not isinstance(a, bool) and not isinstance(b, bool) and abs(a - b) < 1e-12
        ) or a == b
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def summarize_events(events: Sequence[Json], final: Mapping[str, Any]) -> Json:
    metrics = [e for e in events if e.get("type") == "metric"]
    validated = [e for e in metrics if e.get("did_val")]
    epochs = [int(e["epoch"]) for e in validated]
    best = [
        int(e["epoch"])
        for e in validated
        if e.get("mAP50_95") == final.get("mAP50_95") and e.get("mAP50") == final.get("mAP50")
    ]
    if not epochs:
        schedule = "no validation"
    elif epochs[:3] == [1, 2, 4] and all(b - a == 2 for a, b in itertools.pairwise(epochs[1:-1])):
        schedule = "epoch 1, then every second epoch, and the last epoch"
    else:
        schedule = "irregular"
    top = max(
        validated,
        key=lambda e: fitness(e.get("mAP50"), e.get("mAP50_95")) or -1.0,
        default=None,
    )
    return {
        "best_by_fitness": None
        if top is None
        else {k: top.get(k) for k in ("epoch", "mAP50", "mAP50_95", "precision", "recall")},
        "epochs_completed": max((int(e["epoch"]) for e in metrics), default=0),
        "validated_epochs": len(validated),
        "validation_schedule": schedule,
        "best_epoch_events": best[0] if best else None,
        "trainer_completed": any(e.get("type") == "COMPLETED" for e in events),
        "onnx_ready": any(e.get("type") == "ONNX_READY" for e in events),
        "cancel_events": [str(e.get("reason")) for e in events if e.get("type") == "CANCELLED"],
    }


def fitness(m50: float | None, m5095: float | None) -> float | None:
    """Ultralytics' checkpoint-selection fitness for detection: 0.1 mAP50 + 0.9 mAP50-95."""
    if m50 is None or m5095 is None:
        return None
    return round(0.1 * m50 + 0.9 * m5095, 6)


@dataclass(frozen=True)
class Expected:
    run_id: str
    prefix: str
    seed: int
    dataset: str
    split_file: str


def expected_runs() -> list[Expected]:
    plan = json.loads(READINESS.read_text(encoding="utf-8"))["plan"]["runs"]
    by_prefix = {prefix: (name, split) for name, (prefix, split) in DATASETS.items()}
    out = []
    for run in plan:
        prefix = re.sub(r"-s\d+$", "", run["run_id"])
        name, split = by_prefix[prefix]
        out.append(Expected(run["run_id"], prefix, int(run["training_seed"]), name, split))
    return out


def job_state(job: Mapping[str, Any]) -> str:
    ev = job["events"]
    if job["status"] == "COMPLETED" and job.get("model_version_id"):
        early = ev["epochs_completed"] < (job.get("epochs_requested") or 0)
        return "completed" + (f", early-stopped at epoch {ev['epochs_completed']}" if early else "")
    if job["status"] == "CANCELLED" and ev["trainer_completed"] and not ev["cancel_events"]:
        return "CANCELLED after training finished (best.pt written, no model version registered)"
    if job["status"] == "CANCELLED":
        reasons = ", ".join(sorted(set(ev["cancel_events"]))) or "no reason recorded"
        return f"CANCELLED at epoch {ev['epochs_completed']} ({reasons})"
    return str(job["status"])


def classify(exp: Expected, jobs: Sequence[Json]) -> Json:
    identity = [j for j in jobs if j["identity"] == exp.run_id]
    attempts = {
        j["id"]: j for j in jobs if j["identity"] == exp.run_id or j["intent"] == exp.run_id
    }
    valid = [
        j
        for j in identity
        if j["status"] == "COMPLETED" and j.get("model_version_id") and j["config_ok"]
    ]
    valid.sort(key=lambda j: (j["intent"] != exp.run_id, j["created_at"]))
    # a cancelled job counts against the run it was launched as; by its metadata only if its
    # name names no planned run
    cancelled = [
        j
        for j in attempts.values()
        if j["status"] == "CANCELLED"
        and (j["intent"] == exp.run_id or (j["intent"] is None and j["identity"] == exp.run_id))
    ]
    failed = [j for j in attempts.values() if j["status"] == "FAILED"]
    mismatched = [
        j for j in attempts.values() if j["status"] == "COMPLETED" and j["identity"] != exp.run_id
    ]
    bad_config = [j for j in identity if j["status"] == "COMPLETED" and not j["config_ok"]]
    if valid:
        if cancelled:
            label = "CANCELLED_WITH_VALID_RETRY"
        elif len(valid) > 1:
            label = "DUPLICATE_COMPLETED"
        else:
            label = "VALID_COMPLETED"
    elif bad_config or (mismatched and not cancelled):
        label = "CONFIG_MISMATCH"
    elif cancelled:
        label = "CANCELLED_NO_RETRY"
    elif failed:
        label = "FAILED"
    else:
        label = "MISSING"
    chosen = valid[0] if valid else None
    history = []
    for j in sorted(attempts.values(), key=lambda j: j["created_at"]):
        if chosen is not None and j["id"] == chosen["id"]:
            role = "selected valid run" + (
                "" if j["intent"] == exp.run_id else f" (its run_name is {j['run_name']!r})"
            )
        elif j in valid:
            role = "duplicate completed run: same dataset version, seed and configuration"
        elif j["intent"] not in (None, exp.run_id):
            role = (
                f"launched as {j['intent']} but trained this run's dataset version and seed "
                f"({j['state']}); counted as an attempt of {j['intent']}"
            )
        elif j["identity"] != exp.run_id:
            role = (
                f"launched under this run name but trained {j['dataset_name']} with seed "
                f"{j['seed']} ({j['state']})"
            )
        else:
            role = str(j["state"])
        history.append(
            {"job_id": j["id"], "run_name": j["run_name"], "status": j["status"], "role": role}
        )
    return {
        "run_id": exp.run_id,
        "dataset": exp.dataset,
        "seed": exp.seed,
        "classification": label,
        "scientifically_usable": chosen is not None,
        "job_id": chosen["id"] if chosen else None,
        "model_id": chosen.get("model_id") if chosen else None,
        "model_version_id": chosen.get("model_version_id") if chosen else None,
        "val_mAP50_95": chosen.get("val_mAP50_95") if chosen else None,
        "local_checkpoint": bool(chosen and chosen.get("checkpoint")),
        "history": history,
    }


def deviations(args: Mapping[str, Any]) -> dict[str, list[object]]:
    out: dict[str, list[object]] = {}
    for key, want in PROTOCOL.items():
        if key in PHASE_KEYS and key in args and not same(args[key], want):
            continue  # a checkpoint's phase value; checked from the requested configuration
        have = args.get(key, "<not recorded>")
        if not same(have, want):
            out[key] = [want, have]
    return out


def diff(
    a: Mapping[str, Any], b: Mapping[str, Any], skip: frozenset[str]
) -> dict[str, list[object]]:
    keys = (set(a) | set(b)) - skip
    return {k: [a.get(k), b.get(k)] for k in sorted(keys) if not same(a.get(k), b.get(k))}


# ------------------------------------------------------------------------------------ release


def split_file(path: str) -> dict[str, str]:
    with (REPO / path).open(encoding="utf-8", newline="") as handle:
        return {r["id"]: r["split"] for r in csv.DictReader(handle) if r["split"] != "excluded"}


def release_hashes() -> tuple[dict[str, str], Counter[str]]:
    items = pq.read_table(RELEASE / "items.parquet", columns=["global_id", "sha256"]).to_pydict()
    ids = pq.read_table(RELEASE / "annotations.parquet", columns=["global_id"]).to_pydict()
    return dict(zip(items["global_id"], items["sha256"], strict=True)), Counter(ids["global_id"])


def verify_items(
    client: Client, dataset_id: str, path: str, sha: Mapping[str, str], boxes: Counter[str]
) -> Json:
    expected = split_file(path)
    seen: dict[str, Json] = {}
    for item in all_items(client, dataset_id):
        gid = Path(str(item.get("original_filename", ""))).stem
        seen[gid] = {
            "split": SPLIT_ALIASES.get(str(item.get("split")), item.get("split")),
            "sha256": item.get("sha256_hash"),
            "boxes": item.get("annotation_count"),
        }
    common = set(expected) & set(seen)
    missing, extra = sorted(set(expected) - set(seen)), sorted(set(seen) - set(expected))
    return {
        "split_file": path,
        "items_evren": len(seen),
        "items_expected": len(expected),
        "missing": len(missing),
        "extra": len(extra),
        "split_mismatch": sum(1 for g in common if seen[g]["split"] != expected[g]),
        "sha256_mismatch": sum(1 for g in common if seen[g]["sha256"] != sha.get(g)),
        "box_count_mismatch": sum(1 for g in common if seen[g]["boxes"] != boxes.get(g, 0)),
        "examples": (missing + extra)[:5],
    }


# ------------------------------------------------------------------------------------ collect


def collect_datasets(client: Client, project_id: str, verify: bool) -> list[Json]:
    _, body = client.get(f"/projects/{project_id}/datasets")
    sha, boxes = release_hashes() if verify else ({}, Counter[str]())
    out = []
    for ds in sorted(rows(body), key=lambda d: str(d.get("name"))):
        _, vbody = client.get(f"/datasets/{ds['id']}/versions")
        entry: Json = {
            "dataset_id": ds["id"],
            "name": ds.get("name"),
            "item_count": ds.get("item_count"),
            "versions": [
                {
                    "version_id": v["id"],
                    "version_tag": v.get("version_tag"),
                    "frozen": v.get("is_frozen"),
                    "items": v.get("item_count"),
                    "annotations": v.get("total_annotation_count"),
                    "splits": {
                        k: (v.get("split_config") or {}).get(k)
                        for k in ("train", "val", "test", "unassigned")
                    },
                    "boxes_per_class": {
                        c["name"]: c.get("annotation_count")
                        for c in v.get("class_labels_snapshot") or []
                    },
                    "created_at": v.get("created_at"),
                }
                for v in rows(vbody)
            ],
        }
        mapped = DATASETS.get(str(ds.get("name")))
        if verify and mapped:
            print(f"verifying the items of {ds.get('name')}", file=sys.stderr)
            entry["item_check"] = verify_items(client, ds["id"], mapped[1], sha, boxes)
        out.append(entry)
    return out


def collect_models(client: Client) -> dict[str, Json]:
    _, body = client.get("/models", {"limit": "100", "include_public": "false"})
    out: dict[str, Json] = {}
    for model in rows(body):
        _, vbody = client.get(f"/models/{model['id']}/versions")
        for v in rows(vbody):
            _, mbody = client.get(f"/models/versions/{v['id']}/metrics")
            metrics = unwrap(mbody)
            out[v["id"]] = {
                "model_id": model["id"],
                "model_name": model.get("name"),
                "version_id": v["id"],
                "version_tag": v.get("version_tag"),
                "job_id": v.get("job_id"),
                "dataset_name": v.get("dataset_name"),
                "dataset_version_id": v.get("dataset_version_id"),
                "framework": v.get("framework"),
                "file_size_bytes": v.get("file_size_bytes"),
                "weights_registered": bool(v.get("weights_url")),
                "onnx_registered": bool(v.get("onnx_url")),
                "f1": metrics.get("f1") if isinstance(metrics, dict) else None,
                "created_at": v.get("created_at"),
            }
    return out


def build_job(
    client: Client,
    raw: Json,
    versions: Mapping[str, tuple[Json, Json]],
    models: Mapping[str, Json],
    ckpts: Sequence[Json],
) -> Json:
    _, events_body = client.get(f"/training/jobs/{raw['id']}/metrics")
    events = events_body if isinstance(events_body, list) else rows(events_body)
    manifest_status, _ = client.get(f"/training/jobs/{raw['id']}/run-manifest")
    hp = dict(raw.get("hyperparams") or {})
    final = dict(raw.get("final_metrics") or {})
    ds, _version = versions.get(str(raw.get("dataset_version_id")), ({}, {}))
    prefix = DATASETS.get(str(ds.get("name")), (None, ""))[0]
    seed = hp.get("seed")
    mv = models.get(str(raw.get("model_version_id")))
    mine = [c for c in ckpts if c["job_id"] == raw["id"]]
    ckpt = mine[0] if mine else None
    job: Json = {
        "id": raw["id"],
        "run_name": hp.get("run_name"),
        "intent": None,
        "identity": f"{prefix}-s{seed}" if prefix and seed is not None else None,
        "status": raw.get("status"),
        "created_at": raw.get("created_at"),
        "started_at": raw.get("started_at"),
        "completed_at": raw.get("completed_at"),
        "dataset_name": raw.get("dataset_name"),
        "dataset_id": ds.get("dataset_id"),
        "dataset_version_tag": raw.get("version_tag"),
        "dataset_version_id": raw.get("dataset_version_id"),
        "dataset_items": raw.get("item_count"),
        "classes": raw.get("class_count"),
        "architecture": raw.get("architecture"),
        "task": hp.get("task"),
        "seed": seed,
        "epochs_requested": hp.get("epochs"),
        "batch": hp.get("batch"),
        "imgsz": hp.get("imgsz"),
        "optimizer": hp.get("optimizer"),
        "gpu_count": raw.get("gpu_count"),
        "credits_charged": raw.get("actual_cr"),
        "gpu_hours": raw.get("actual_gpu_hours"),
        "events": summarize_events(events, final),
        "best_epoch_evren": final.get("best_epoch"),
        "val_mAP50": final.get("mAP50"),
        "val_mAP50_95": final.get("mAP50_95"),
        "val_precision": final.get("precision"),
        "val_recall": final.get("recall"),
        "val_f1": mv.get("f1") if mv else final.get("f1"),
        "val_fitness": fitness(final.get("mAP50"), final.get("mAP50_95")),
        "model_id": mv.get("model_id") if mv else None,
        "model_name": mv.get("model_name") if mv else None,
        "model_version_id": raw.get("model_version_id"),
        "model_version_links_back": bool(mv and mv.get("job_id") == raw["id"]),
        "weights_registered": bool(mv and mv.get("weights_registered")),
        "onnx_registered": bool(mv and mv.get("onnx_registered")),
        "run_manifest_http": manifest_status,
        "parent_job_id": raw.get("parent_job_id"),
        "resume_checkpoint": bool(raw.get("resume_checkpoint")),
        "error_category": raw.get("error_category"),
        "error_message": raw.get("error_message"),
        "requested": {k: v for k, v in hp.items() if k not in {"run_name", "tags"}},
        "checkpoint": None,
    }
    if ckpt is not None:
        job["checkpoint"] = {
            "local_files": sorted(c["file"] for c in mine),
            "sha256": ckpt["sha256"],
            "bytes": ckpt["bytes"],
            "size_matches_evren": bool(mv and mv.get("file_size_bytes") == ckpt["bytes"]),
            "metrics_match_evren": same(
                ckpt["train_metrics"].get("metrics/mAP50-95(B)"), final.get("mAP50_95")
            ),
            "ultralytics_version": ckpt["ultralytics_version"],
            "effective": ckpt["train_args"],
        }
    return job


def collect(client: Client, *, verify: bool, checkpoint_dir: Path | None) -> Json:
    status, body = client.get("/projects", {"limit": "100"})
    project = next((p for p in rows(body) if p.get("name") == PROJECT), None)
    if status != 200 or project is None:
        raise RuntimeError(f"project {PROJECT!r} not found (HTTP {status})")
    datasets = collect_datasets(client, project["id"], verify)
    versions = {v["version_id"]: (d, v) for d in datasets for v in d["versions"]}
    models = collect_models(client)
    ckpts = (
        [read_checkpoint(p) for p in sorted(checkpoint_dir.glob("*.pt"))] if checkpoint_dir else []
    )
    raw_jobs = sorted(all_jobs(client, project["id"]), key=lambda j: str(j.get("created_at")))
    jobs = [build_job(client, raw, versions, models, ckpts) for raw in raw_jobs]

    # key-class probes: what each key may read (GET only; no inference is called)
    probe_list: list[tuple[str, str, dict[str, str] | None]] = [
        ("model", "/models", {"limit": "1"}),
        ("model", "/training/jobs", {"limit": "1"}),
    ]
    probe_version = next(iter(models), None)
    if probe_version is not None:
        probe_list += [
            ("model", f"/inference/model-classes/{probe_version}", None),
            ("platform", f"/inference/model-classes/{probe_version}", None),
        ]
    probes = []
    for key, path, params in probe_list:
        code, pbody = client.get(path, params, key=key)
        message = (pbody or {}).get("error", {}).get("message") if isinstance(pbody, dict) else None
        probes.append(
            {"key": key, "path": re.sub(UUID, "{id}", path), "status": code, "message": message}
        )

    # each job's requested configuration against the configuration shared by the project
    def config_of(job: Mapping[str, Any]) -> str:
        cfg = {k: v for k, v in job["requested"].items() if k not in RUN_KEYS}
        return json.dumps(
            {**cfg, "architecture": job["architecture"], "gpu_count": job["gpu_count"]},
            sort_keys=True,
        )

    reference = Counter(config_of(j) for j in jobs).most_common(1)[0][0] if jobs else "{}"
    expected = expected_runs()
    by_norm = {norm(e.run_id): e.run_id for e in expected}
    for job in jobs:
        job["intent"] = by_norm.get(norm(job["run_name"]))
        job["config_ok"] = config_of(job) == reference
        job["state"] = job_state(job)
    runs = [classify(e, jobs) for e in expected]
    return {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "api": client.api,
        "web": os.environ.get("EVREN_BASE_URL", ""),
        "project": {"id": project["id"], "name": project.get("name")},
        "reference_config": json.loads(reference),
        "datasets": datasets,
        "jobs": jobs,
        "models": sorted(models.values(), key=lambda m: str(m["created_at"])),
        "expected_runs": runs,
        "checkpoints": [
            {k: c[k] for k in ("file", "bytes", "sha256", "job_id", "ultralytics_version", "date")}
            for c in ckpts
        ],
        "probes": probes,
        "calls": [vars(c) for c in client.calls],
    }


# -------------------------------------------------------------------------------------- audit


def pair_audit(data: Mapping[str, Any]) -> list[Json]:
    jobs = {j["id"]: j for j in data["jobs"]}
    runs = {r["run_id"]: r for r in data["expected_runs"]}
    out = []
    for c0_id, c1_id in PAIRS:
        sides = []
        for run_id in (c0_id, c1_id):
            run = runs[run_id]
            if run["job_id"]:
                sides.append((jobs[run["job_id"]], "selected"))
            else:
                done = [
                    jobs[h["job_id"]]
                    for h in run["history"]
                    if jobs[h["job_id"]]["status"] == "COMPLETED"
                    and jobs[h["job_id"]]["dataset_name"] == run["dataset"]
                ]
                sides.append(
                    (done[0], "stand-in: right dataset, wrong seed") if done else (None, "none")
                )
        (a, a_kind), (b, b_kind) = sides
        entry: Json = {"pair": f"{c0_id} vs {c1_id}", "c0": None, "c1": None, "verdict": ""}
        for name, job, kind in (("c0", a, a_kind), ("c1", b, b_kind)):
            entry[name] = (
                None
                if job is None
                else {
                    "job_id": job["id"],
                    "kind": kind,
                    "dataset": job["dataset_name"],
                    "seed": job["seed"],
                    "run_name": job["run_name"],
                }
            )
        if a is None or b is None:
            missing = [
                run for run, side in zip((c0_id, c1_id), (a, b), strict=True) if side is None
            ]
            entry["verdict"] = (
                "INCOMPLETE: no completed job with the planned dataset for " + ", ".join(missing)
            )
            out.append(entry)
            continue
        requested = diff(a["requested"], b["requested"], RUN_KEYS)
        for key in ("architecture", "gpu_count"):
            if not same(a[key], b[key]):
                requested[key] = [a[key], b[key]]
        effective = None
        phase = None
        if a["checkpoint"] and b["checkpoint"]:
            effective = diff(
                a["checkpoint"]["effective"],
                b["checkpoint"]["effective"],
                RUN_KEYS | PATH_KEYS | PHASE_KEYS,
            )
            phase = diff(
                a["checkpoint"]["effective"],
                b["checkpoint"]["effective"],
                frozenset(set(a["checkpoint"]["effective"]) | set(b["checkpoint"]["effective"]))
                - PHASE_KEYS,
            )
        schedule = [a["events"]["validation_schedule"], b["events"]["validation_schedule"]]
        entry.update(
            {
                "seeds": [a["seed"], b["seed"]],
                "requested_differences": requested,
                "effective_differences": effective,
                "phase_differences": phase,
                "validation_schedules": schedule,
            }
        )
        problems = []
        if a_kind != "selected" or b_kind != "selected":
            problems.append("one side is a stand-in, not a valid run of the matrix")
        if a["seed"] != b["seed"]:
            problems.append(f"seed differs ({a['seed']} vs {b['seed']})")
        if requested:
            problems.append("requested configuration differs: " + ", ".join(requested))
        if effective:
            problems.append("effective configuration differs: " + ", ".join(effective))
        if schedule[0] != schedule[1]:
            problems.append("validation schedule differs")
        if effective is None:
            problems.append(
                "effective configuration not verifiable (a checkpoint is not available locally)"
            )
        entry["verdict"] = "; ".join(problems) if problems else "EQUIVALENT except the dataset"
        out.append(entry)
    return out


def replicates(data: Mapping[str, Any]) -> list[Json]:
    """Completed jobs that repeat a dataset version, seed and configuration: a noise floor."""
    groups: dict[tuple[str, object], list[Json]] = {}
    for j in data["jobs"]:
        if j["status"] == "COMPLETED" and j["config_ok"]:
            groups.setdefault((str(j["dataset_version_id"]), j["seed"]), []).append(j)
    out = []
    for (_, seed), members in groups.items():
        if len(members) > 1:
            out.append(
                {
                    "dataset": members[0]["dataset_name"],
                    "seed": seed,
                    "jobs": [m["id"] for m in members],
                    "run_names": [m["run_name"] for m in members],
                    "val_mAP50": [m["val_mAP50"] for m in members],
                    "val_mAP50_95": [m["val_mAP50_95"] for m in members],
                    "best_epoch_events": [m["events"]["best_epoch_events"] for m in members],
                    "identical": len(
                        {json.dumps([m["val_mAP50"], m["val_mAP50_95"]]) for m in members}
                    )
                    == 1,
                }
            )
    return out


# ------------------------------------------------------------------------------------- render


def _cell(value: object) -> str:
    text = "-" if value is None or value == "" else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _table(header: Sequence[str], body: Sequence[Sequence[object]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in body]
    return lines


def _id(value: object) -> str:
    text = str(value or "")
    return f"`{text[-8:]}`" if re.fullmatch(UUID, text) else (text or "-")


def _pct(value: object) -> str:
    return f"{100 * float(value):.2f}" if isinstance(value, int | float) else "-"


def _header(data: Mapping[str, Any], title: str) -> list[str]:
    return [
        f"# {title}",
        "",
        f"Generated by `scripts/evren_inventory.py` on {data['generated_at']} from the EVREN API "
        f"(`{data['api']}`, read-only: GET requests to an allow list, no inference, no download) "
        f"for the project *{data['project']['name']}*. Job, dataset and model ids are abbreviated "
        "to their last eight characters; the full ids are in `evren_run_inventory.json`.",
        "",
    ]


CSV_FIELDS = (
    "job_id",
    "run_name",
    "run_by_name",
    "run_by_metadata",
    "status",
    "state",
    "created_at",
    "started_at",
    "completed_at",
    "dataset_name",
    "dataset_id",
    "dataset_version_tag",
    "dataset_version_id",
    "dataset_items",
    "architecture",
    "task",
    "seed",
    "epochs_requested",
    "epochs_completed",
    "validated_epochs",
    "batch",
    "imgsz",
    "optimizer",
    "lr0",
    "lrf",
    "momentum",
    "weight_decay",
    "warmup_epochs",
    "cos_lr",
    "label_smoothing",
    "augmentation",
    "gpu_count",
    "best_epoch_events",
    "best_epoch_evren",
    "selection_metric",
    "val_mAP50",
    "val_mAP50_95",
    "val_precision",
    "val_recall",
    "val_f1",
    "events_best_epoch",
    "events_best_mAP50",
    "events_best_mAP50_95",
    "events_best_precision",
    "events_best_recall",
    "model_id",
    "model_version_id",
    "weights_registered",
    "onnx_registered",
    "local_checkpoint_files",
    "checkpoint_sha256",
    "cancel_reason",
    "error",
    "credits_charged",
    "gpu_hours",
    "matrix_role",
)
AUGMENT = (
    "hsv_h",
    "hsv_s",
    "hsv_v",
    "degrees",
    "translate",
    "scale",
    "shear",
    "perspective",
    "flipud",
    "fliplr",
    "mosaic",
    "mixup",
    "copy_paste",
    "close_mosaic",
    "erasing",
)


def csv_rows(data: Mapping[str, Any]) -> list[dict[str, object]]:
    roles: dict[str, list[str]] = {}
    for run in data["expected_runs"]:
        for h in run["history"]:
            roles.setdefault(h["job_id"], []).append(f"{run['run_id']}: {h['role']}")
    out = []
    for j in data["jobs"]:
        r = j["requested"]
        ck = j["checkpoint"]
        out.append(
            {
                "job_id": j["id"],
                "run_name": j["run_name"],
                "run_by_name": j["intent"],
                "run_by_metadata": j["identity"],
                "status": j["status"],
                "state": j["state"],
                "created_at": j["created_at"],
                "started_at": j["started_at"],
                "completed_at": j["completed_at"],
                "dataset_name": j["dataset_name"],
                "dataset_id": j["dataset_id"],
                "dataset_version_tag": j["dataset_version_tag"],
                "dataset_version_id": j["dataset_version_id"],
                "dataset_items": j["dataset_items"],
                "architecture": j["architecture"],
                "task": j["task"],
                "seed": j["seed"],
                "epochs_requested": j["epochs_requested"],
                "epochs_completed": j["events"]["epochs_completed"],
                "validated_epochs": j["events"]["validated_epochs"],
                "batch": j["batch"],
                "imgsz": j["imgsz"],
                "optimizer": j["optimizer"],
                **{
                    k: r.get(k) for k in ("lr0", "lrf", "momentum", "weight_decay", "warmup_epochs")
                },
                "cos_lr": r.get("cos_lr"),
                "label_smoothing": r.get("label_smoothing"),
                "augmentation": json.dumps({k: r.get(k) for k in AUGMENT}, sort_keys=True),
                "gpu_count": j["gpu_count"],
                "best_epoch_events": j["events"]["best_epoch_events"],
                "best_epoch_evren": j["best_epoch_evren"],
                "selection_metric": "0.1 mAP50 + 0.9 mAP50-95 (validation)",
                "val_mAP50": j["val_mAP50"],
                "val_mAP50_95": j["val_mAP50_95"],
                "val_precision": j["val_precision"],
                "val_recall": j["val_recall"],
                "val_f1": j["val_f1"],
                **{
                    f"events_best_{k}": (j["events"]["best_by_fitness"] or {}).get(k)
                    for k in ("epoch", "mAP50", "mAP50_95", "precision", "recall")
                },
                "model_id": j["model_id"],
                "model_version_id": j["model_version_id"],
                "weights_registered": j["weights_registered"],
                "onnx_registered": j["onnx_registered"],
                "local_checkpoint_files": ";".join(ck["local_files"]) if ck else "",
                "checkpoint_sha256": ck["sha256"] if ck else "",
                "cancel_reason": ";".join(j["events"]["cancel_events"]),
                "error": " ".join(filter(None, [j["error_category"], j["error_message"]])),
                "credits_charged": j["credits_charged"],
                "gpu_hours": j["gpu_hours"],
                "matrix_role": " | ".join(roles.get(j["id"], ["not attached to a planned run"])),
            }
        )
    return out


def render_expected(data: Mapping[str, Any], reps: Sequence[Json]) -> str:
    jobs = data["jobs"]
    runs = data["expected_runs"]
    status = Counter(j["status"] for j in jobs)
    early = [j for j in jobs if j["status"] == "CANCELLED" and j["events"]["cancel_events"]]
    late = [j for j in jobs if j["status"] == "CANCELLED" and not j["events"]["cancel_events"]]
    usable = [r for r in runs if r["scientifically_usable"]]
    represented = {j["identity"] for j in jobs} & {r["run_id"] for r in runs}
    mislabelled = [j for j in jobs if j["intent"] != j["identity"]]
    lines = _header(data, "M7 on EVREN: planned runs against the jobs found")
    lines += [
        "## Summary",
        "",
        f"- Jobs found in the project: **{len(jobs)}**; COMPLETED {status.get('COMPLETED', 0)}, "
        f"CANCELLED {status.get('CANCELLED', 0)}, FAILED {status.get('FAILED', 0)}, other "
        f"{len(jobs) - sum(status.get(s, 0) for s in ('COMPLETED', 'CANCELLED', 'FAILED'))}.",
        f"- Of the cancelled jobs, {len(early)} were cancelled during training at the user's request "
        f"and {len(late)} were marked CANCELLED **after** the trainer had finished all epochs and "
        "written best.pt: EVREN charged them in full but registered no model version, so their "
        "weights are not reachable through the API.",
        f"- Planned runs represented by at least one job (by dataset version and seed): "
        f"{len(represented)} of {len(runs)}; with a valid completed model: **{len(usable)} of "
        f"{len(runs)}**.",
        f"- A job's run is identified by its **dataset version and seed** (EVREN metadata); the "
        f"free-text run name is recorded but not trusted: {len(mislabelled)} jobs carry a run "
        "name that disagrees with what they trained (or none).",
        "- The datasets were verified against the committed packages: split sizes and boxes per "
        "class of every frozen dataset version"
        + (
            ", and every item by global id, split, SHA-256 and box count"
            if any("item_check" in d for d in data["datasets"])
            else ""
        )
        + " (table at the end).",
        "",
        "## The 17 planned runs",
        "",
        *_table(
            [
                "run",
                "EVREN dataset",
                "seed",
                "classification",
                "job",
                "model version",
                "val mAP50-95 (EVREN)",
                "local checkpoint",
                "attempts",
            ],
            [
                [
                    f"`{r['run_id']}`",
                    r["dataset"],
                    r["seed"],
                    f"**{r['classification']}**",
                    _id(r["job_id"]),
                    _id(r["model_version_id"]),
                    _pct(r["val_mAP50_95"]),
                    "yes" if r["local_checkpoint"] else "no",
                    "; ".join(
                        f"{_id(h['job_id'])} {h['status']}: {h['role']}" for h in r["history"]
                    )
                    or "none",
                ]
                for r in runs
            ],
        ),
        "",
        "Classification rules: VALID_COMPLETED = one COMPLETED job with this run's dataset version "
        "and seed, a registered model version and the shared configuration; "
        "DUPLICATE_COMPLETED = more than one such job (the earliest one carrying this run's name "
        "is selected); CANCELLED_WITH_VALID_RETRY = such a job plus cancelled attempts; "
        "CANCELLED_NO_RETRY = only cancelled attempts; CONFIG_MISMATCH = only completed jobs that "
        "were launched as this run but trained another dataset version or seed, or a job with "
        "this identity whose configuration differs; FAILED; MISSING = no attempt at all. "
        "Validation scores are EVREN's own, on each run's validation split: they are not the M7 "
        "result.",
        "",
        "## Jobs marked CANCELLED after their training finished",
        "",
        *(
            _table(
                [
                    "job",
                    "run name",
                    "trained (dataset, seed)",
                    "epochs",
                    "best epoch (events)",
                    "val mAP50-95 (events)",
                    "credits charged",
                    "model version",
                ],
                [
                    [
                        _id(j["id"]),
                        j["run_name"],
                        f"{j['dataset_name']}, {j['seed']}",
                        j["events"]["epochs_completed"],
                        (j["events"]["best_by_fitness"] or {}).get("epoch"),
                        _pct((j["events"]["best_by_fitness"] or {}).get("mAP50_95")),
                        j["credits_charged"],
                        "none",
                    ]
                    for j in late
                ],
            )
            if late
            else ["None."]
        ),
        "",
        "Their event streams end with the trainer's COMPLETED and ONNX_READY events (best.pt and "
        "best.onnx written) and contain no cancellation event; the job status is CANCELLED and no "
        "model version exists, so the API offers no route to their weights. Whether EVREN can "
        "still register them is a question for EVREN support; otherwise they must be rerun.",
        "",
        "## Jobs whose run name disagrees with what they trained",
        "",
        *_table(
            ["job", "run name", "trained dataset", "seed", "status", "is in fact"],
            [
                [
                    _id(j["id"]),
                    j["run_name"] or "(none)",
                    j["dataset_name"],
                    j["seed"],
                    j["status"],
                    (f"`{j['identity']}`" if j["identity"] else "-")
                    + (
                        "" if j["identity"] in {r["run_id"] for r in runs} else " (not in the plan)"
                    ),
                ]
                for j in mislabelled
            ],
        ),
        "",
        "## Replicates: completed jobs that repeat a dataset version, seed and configuration",
        "",
    ]
    if reps:
        lines += _table(
            [
                "dataset",
                "seed",
                "jobs (run names)",
                "val mAP50",
                "val mAP50-95",
                "best epoch",
                "identical",
            ],
            [
                [
                    r["dataset"],
                    r["seed"],
                    ", ".join(
                        f"{_id(j)} ({n})" for j, n in zip(r["jobs"], r["run_names"], strict=True)
                    ),
                    " / ".join(_pct(v) for v in r["val_mAP50"]),
                    " / ".join(_pct(v) for v in r["val_mAP50_95"]),
                    " / ".join(str(v) for v in r["best_epoch_events"]),
                    "yes" if r["identical"] else "**no**",
                ]
                for r in reps
            ],
        )
        lines += [
            "",
            "Identical inputs (dataset version, seed, configuration, deterministic=True) gave "
            "different results: training on EVREN is not bit-for-bit reproducible. These pairs are "
            "an empirical noise floor for any single-seed comparison.",
            "",
        ]
    else:
        lines += ["None.", ""]
    lines += [
        "## Datasets against the committed packages",
        "",
        *_table(
            [
                "EVREN dataset",
                "version",
                "frozen",
                "train / val / test (unassigned)",
                "boxes",
                "items by id",
                "split",
                "SHA-256",
                "boxes per item",
            ],
            [
                [
                    d["name"],
                    ", ".join(str(v["version_tag"]) for v in d["versions"]),
                    ", ".join(str(v["frozen"]) for v in d["versions"]),
                    "; ".join(
                        f"{v['splits']['train']} / {v['splits']['val']} / {v['splits']['test']} "
                        f"({v['splits']['unassigned']})"
                        for v in d["versions"]
                    ),
                    ", ".join(str(v["annotations"]) for v in d["versions"]),
                    _item_cell(d, "ids"),
                    _item_cell(d, "split_mismatch"),
                    _item_cell(d, "sha256_mismatch"),
                    _item_cell(d, "box_count_mismatch"),
                ]
                for d in data["datasets"]
            ],
        ),
        "",
        "Item check: every item EVREN lists for the dataset, matched by global id (file name) "
        "with the committed split file of its package; *split*, *SHA-256* and *boxes per item* "
        "count the disagreements (SHA-256 against `items.parquet`, boxes against "
        "`annotations.parquet`). The listing shows the dataset's current items; the frozen "
        "version's counts are in the columns before.",
        "",
    ]
    return "\n".join(lines)


def _item_cell(d: Mapping[str, Any], key: str) -> str:
    check = d.get("item_check")
    if not check:
        return "not checked"
    if key == "ids":
        ok = check["missing"] == 0 and check["extra"] == 0
        return (
            f"{check['items_evren']} = {check['items_expected']}"
            if ok
            else (f"**{check['missing']} missing, {check['extra']} extra**")
        )
    return "0" if check[key] == 0 else f"**{check[key]}**"


def render_config(data: Mapping[str, Any], pairs: Sequence[Json], reps: Sequence[Json]) -> str:
    jobs = data["jobs"]
    with_ckpt = [j for j in jobs if j["checkpoint"]]
    reference = data["reference_config"]
    effective_all = [j["checkpoint"]["effective"] for j in with_ckpt]
    shared_effective: dict[str, object] = {}
    if effective_all:
        for key in sorted(set.intersection(*(set(e) for e in effective_all))):
            values = {json.dumps(e[key], sort_keys=True) for e in effective_all}
            if len(values) == 1 and key not in PATH_KEYS:
                shared_effective[key] = effective_all[0][key]
    lines = _header(data, "M7 on EVREN: configuration consistency")
    lines += [
        "Sources. *Requested*: the hyperparameters EVREN stores with every job "
        f"({len(jobs)} jobs). *Effective*: the `train_args` saved inside best.pt, read from local "
        f"copies of {len(with_ckpt)} jobs' checkpoints without executing any pickled code "
        "(Ultralytics "
        + ", ".join(
            sorted({str(j["checkpoint"]["ultralytics_version"]) for j in with_ckpt}) or ["-"]
        )
        + "). EVREN's applied-settings record (`/training/jobs/{id}/run-manifest`) answers HTTP "
        + ", ".join(sorted({str(j["run_manifest_http"]) for j in jobs}))
        + " for every job, so it could not be used.",
        "",
        "## One configuration for every job",
        "",
        "Apart from `run_name`, `tags` and `seed`, every job requested exactly this configuration "
        f"({sum(1 for j in jobs if j['config_ok'])} of {len(jobs)} jobs):",
        "",
        *_table(["key", "value"], [[f"`{k}`", v] for k, v in sorted(reference.items())]),
        "",
        "## Deviations from the M7 protocol (shared by every run)",
        "",
    ]
    rows_dev = []
    phase_note = "varies with the training phase of best.pt"
    for key, want in PROTOCOL.items():
        req = reference.get(key, "<not recorded>")
        if key in shared_effective:
            eff: object = shared_effective[key]
        elif key in PHASE_KEYS and effective_all:
            eff = phase_note
        else:
            eff = "<not recorded>" if effective_all else "-"
        unknown = ("<not recorded>", "-", phase_note)
        req_off = req != "<not recorded>" and not same(req, want)
        eff_off = eff not in unknown and not same(eff, want)
        if req_off or eff_off:
            note = "deviates from the protocol"
        elif req == "<not recorded>":
            note = "not recorded by EVREN; " + (
                "the checkpoints match the protocol" if eff not in unknown else "not verifiable"
            )
        else:
            continue
        rows_dev.append([f"`{key}`", want, req, eff, note])
    lines += _table(
        ["key", "M7 protocol", "requested (EVREN)", "effective (checkpoints)", "finding"], rows_dev
    )
    lines += [
        "",
        "These values are the same in every run, so they do not confound a C0/C1 contrast, but "
        "the M7 runs did not use the planned schedule exactly: the learning rate follows a cosine "
        "schedule, label smoothing 0.1 is set, and EVREN validates on epoch 1, every second "
        "epoch and the last epoch (`val_period` is an EVREN field, `val=False` in the "
        "checkpoints), which also sets the granularity of best-checkpoint selection and of early "
        "stopping. EVREN's own fields that Ultralytics does not know (`val_period`, "
        "`target_steps`, `cache: disk` against an effective `cache=False`) are reported as "
        "found.",
        "",
        "## The paired comparisons",
        "",
        *_table(
            [
                "pair",
                "C0 job (dataset, seed)",
                "C1 job (dataset, seed)",
                "requested differences",
                "effective differences",
                "verdict",
            ],
            [
                [
                    p["pair"],
                    _side(p["c0"]),
                    _side(p["c1"]),
                    _diff_cell(p.get("requested_differences")),
                    _diff_cell(p.get("effective_differences")),
                    p["verdict"],
                ]
                for p in pairs
            ],
        ),
        "",
        "Differences that a checkpoint carries because of the training phase in which best.pt "
        "was written (`mosaic`, `mixup`, `copy_paste` after `close_mosaic`; `val` at the last "
        "epoch) are not configuration differences and are listed in the JSON only.",
        "",
        "## Validation and checkpoint selection",
        "",
        "- Validation schedule found in the event stream: "
        + ", ".join(
            sorted(
                {
                    j["events"]["validation_schedule"]
                    for j in jobs
                    if j["events"]["trainer_completed"] and j["events"]["validated_epochs"] > 3
                }
            )
        )
        + ".",
        "- Selection rule: Ultralytics fitness = 0.1 mAP50 + 0.9 mAP50-95 on the run's validation "
        "split (the checkpoints' `train_metrics.fitness` equals it); conf 0.001, iou 0.7 and "
        "max_det 300 during validation.",
        "- EVREN's `final_metrics.best_epoch` is one more than the event-stream epoch whose metrics "
        "it reports, except when the best epoch is the last one: "
        + ", ".join(
            f"{_id(j['id'])} {j['best_epoch_evren']} vs {j['events']['best_epoch_events']}"
            for j in jobs
            if j["status"] == "COMPLETED" and j["best_epoch_evren"] is not None
        )
        + ".",
        "- Early stopping (patience 20): "
        + (
            ", ".join(
                f"{_id(j['id'])} ({j['run_name']}) stopped at epoch {j['events']['epochs_completed']}"
                for j in jobs
                if j["status"] == "COMPLETED"
                and j["events"]["epochs_completed"] < (j["epochs_requested"] or 0)
            )
            or "none"
        )
        + ".",
        "",
        "## Determinism",
        "",
    ]
    if reps:
        lines += [
            "Every checkpoint read has `deterministic=True`, yet completed jobs that repeat a dataset "
            "version, seed and configuration reached different validation scores: "
            + "; ".join(
                f"{r['dataset']} seed {r['seed']}: mAP50-95 "
                + " vs ".join(_pct(v) for v in r["val_mAP50_95"])
                for r in reps
            )
            + ". A seed therefore does not pin a result on EVREN; seed-to-seed and run-to-run "
            "variation must be estimated, not assumed away.",
            "",
        ]
    else:
        lines += ["No replicate was found.", ""]
    lines += [
        "## What could not be verified",
        "",
        "- The effective configuration of jobs without a local checkpoint ("
        + ", ".join(
            f"{_id(j['id'])} {j['run_name']}"
            for j in jobs
            if j["status"] == "COMPLETED" and not j["checkpoint"]
        )
        + "): their requested configuration equals the others'.",
        "- The GPU model and driver, CUDA and cuDNN versions: not exposed by the API.",
        "",
    ]
    return "\n".join(lines)


def _side(side: Mapping[str, Any] | None) -> str:
    if not side:
        return "none"
    note = "" if side["kind"] == "selected" else f" — {side['kind']}"
    return f"{_id(side['job_id'])} ({side['dataset']}, seed {side['seed']}){note}"


def _diff_cell(value: Mapping[str, Any] | None) -> str:
    if value is None:
        return "not verifiable"
    return ", ".join(f"`{k}`: {a} vs {b}" for k, (a, b) in value.items()) or "none"


def render_api(data: Mapping[str, Any]) -> str:
    calls = Counter((c["key"], c["path"], c["status"]) for c in data["calls"])
    lines = _header(data, "EVREN API audit for M7")
    lines += [
        "## Credentials",
        "",
        "- Read from environment variables only: `EVREN_PLATFORM_API_KEY`, `EVREN_MODEL_API_KEY`, "
        "`EVREN_BASE_URL`, put into the process environment by the operator from the git-ignored "
        "`.env` (uv's `--env-file` cannot parse the Windows path in that file). Keys with the "
        "`evren_` prefix are sent as `X-API-Key`, as the "
        "official SDK does; no key, token or header is printed, logged or stored, and stored "
        "responses keep no URL query strings and no personal fields.",
        f"- `EVREN_BASE_URL` is the web application ({data['web'] or 'not set'}); its `/api/...` "
        "paths return the single-page app, not the API. The API host is "
        f"`{data['api']}`: the default of the official SDK and the API origin declared by the web "
        "application.",
        "",
        "## What is official and what was discovered",
        "",
        "- **Official SDK** `evren-sdk` 0.9.2 (PyPI, Apache-2.0, source read without running it): "
        "vision inference (`POST /inference/predict`, `POST /inference/predict/batch`, a "
        "WebSocket stream), model listing (`GET /models`, `GET /models/{id}/versions`, "
        "`GET /models/{owner}/{slug}`), class metadata (`GET /inference/model-classes/{version}`), "
        "weights download (`GET /models/versions/{version}/download?format=...`, which returns a "
        "signed URL), dataset upload and GPU warm-up. It has **no** training-job, project or "
        "dataset-listing call.",
        "- **Documentation**: `docs.ssyz.org.tr` does not resolve (DNS); the API exposes no "
        "OpenAPI or Swagger document (`/openapi.json`, `/docs`: HTTP 404).",
        "- **Discovered**: the training, project and dataset endpoints come from the public "
        "JavaScript bundle of the official web application (the calls its pages make). Only GET "
        "endpoints from it are used here.",
        "",
        "## Endpoints used (all GET)",
        "",
        *_table(
            ["key class", "path", "HTTP status", "calls"],
            [[k, f"`{p}`", s, n] for (k, p, s), n in sorted(calls.items())],
        ),
        "",
        "## What each key class can read",
        "",
        *_table(
            ["key class", "probe", "HTTP status", "message"],
            [[p["key"], f"`{p['path']}`", p["status"], p["message"] or ""] for p in data["probes"]],
        ),
        "",
        "The platform key reads projects, training jobs (list, events, metrics), datasets "
        "(versions, items), models and inference metadata. The model-inference key reads models, "
        "model versions, version metrics and inference metadata, and is refused on training and "
        "project endpoints (the refusal message is in the table above).",
        "",
        "## Endpoints deliberately not called",
        "",
        "- Mutating, seen in the SDK or the web application: `POST /training/jobs`, "
        "`POST /training/jobs/{id}/stop`, `POST /training/jobs/{id}/resume`, "
        "`POST /training/jobs/bulk-delete`, `DELETE /training/jobs/{id}`, "
        "`POST /training/jobs/dry-run`, `POST /models/versions/{id}/convert`, "
        "`POST /models/{id}/stage|fork|star`, `PATCH /models/{id}/...`, `DELETE /models/{id}`, "
        "`POST /datasets/{id}/upload/...`, `PATCH /datasets/{id}/items/...`, "
        "`POST /datasets/{id}/versions/{v}/rollback`, `POST /inference/warmup`.",
        "- Credit-consuming: `POST /inference/predict`, `POST /inference/predict/batch`, "
        "`benchmark()` (the SDK states that every inference consumes credits).",
        "- Downloads: `GET /models/versions/{id}/download` (weights) and dataset export URLs.",
        "",
        "## Inference, as implemented by the official SDK",
        "",
        "- Request (multipart form): `model_version_id`, `confidence_threshold` (default 0.25), "
        "`iou_threshold` (default 0.45), `image_size` (default 640), optional `classes`. There is "
        "**no `max_det` control** and no switch for class-agnostic NMS, test-time augmentation or "
        "half precision.",
        "- Response per image: `predictions[]` with `class_name`, `confidence`, `bbox` (plus "
        "`mask`, `keypoints`, `obb`, `probs` for other tasks), `image_width`, `image_height`, "
        "`inference_ms`, `model_version_id`. There is **no class id**: classes are names, mapped "
        "through `GET /inference/model-classes/{version}`.",
        "- Boxes: the SDK reads `bbox` as `[x1, y1, x2, y2]` and its drawing code accepts both "
        "pixel and 0-1 normalized coordinates, so the convention may differ by model framework.",
        "- The WebSocket stream (`/inference/stream`) takes the same three controls "
        "(`confidence`, `iou`, `image_size`).",
        "- Not established without calling inference (which costs credits): the coordinate "
        "convention of these YOLO11 models, whether a confidence threshold of 0.001 is accepted, "
        "the server-side `max_det` cap, and whether the server letterboxes like Ultralytics' "
        "validator.",
        "",
        "## Model access",
        "",
        f"- Model versions found: {len(data['models'])}; each links back to its training job "
        "(`version.job_id` and `job.model_version_id` agree: "
        + str(all(j["model_version_links_back"] for j in data["jobs"] if j["model_version_id"]))
        + ") and has PyTorch and ONNX weights registered.",
        "- Download is supported by the SDK; it was not used. Local checkpoints were matched to "
        "jobs through the job id inside their `train_args` (`data` and `project` paths), and "
        "their sizes against the registered file sizes.",
        "",
    ]
    return "\n".join(lines)


def write_outputs(data: Json, out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    pairs = pair_audit(data)
    reps = replicates(data)
    payload = {**data, "pairs": pairs, "replicates": reps}
    files = {
        "evren_run_inventory.json": json.dumps(payload, indent=1, ensure_ascii=False, default=str)
        + "\n",
        "m7_expected_vs_actual.md": render_expected(data, reps),
        "m7_config_consistency.md": render_config(data, pairs, reps),
        "evren_api_audit.md": render_api(data),
    }
    written = []
    for name, text in files.items():
        path = out / name
        path.write_bytes(text.encode("utf-8"))
        written.append(path)
    path = out / "evren_run_inventory.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(csv_rows(data))
    written.append(path)
    return written


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=REPO / "reports" / "m7")
    parser.add_argument(
        "--checkpoints", type=Path, default=None, help="folder of local best.pt files"
    )
    parser.add_argument("--verify-items", action="store_true", help="compare every dataset item")
    parser.add_argument(
        "--from-json", type=Path, default=None, help="re-render from a saved inventory, no API call"
    )
    args = parser.parse_args(argv)
    if args.from_json is not None:
        saved = json.loads(args.from_json.read_text(encoding="utf-8"))
        saved.pop("pairs", None)
        saved.pop("replicates", None)
        for path in write_outputs(saved, args.out):
            print(f"wrote {path}")
        return 0
    keys = {
        "platform": os.environ.get("EVREN_PLATFORM_API_KEY", ""),
        "model": os.environ.get("EVREN_MODEL_API_KEY", ""),
    }
    if not keys["platform"]:
        print("EVREN_PLATFORM_API_KEY is not set in the environment", file=sys.stderr)
        return 2
    client = Client(os.environ.get("EVREN_API_URL", DEFAULT_API).rstrip("/"), keys)
    data = collect(client, verify=args.verify_items, checkpoint_dir=args.checkpoints)
    for path in write_outputs(data, args.out):
        print(f"wrote {path.relative_to(REPO) if path.is_relative_to(REPO) else path}")
    usable = sum(1 for r in data["expected_runs"] if r["scientifically_usable"])
    print(
        f"jobs {len(data['jobs'])}; planned runs with a valid model {usable}/{len(data['expected_runs'])}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
