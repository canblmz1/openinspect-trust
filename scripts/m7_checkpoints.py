"""Download, verify and register the M7 checkpoints through EVREN's model-version download API.

Reads the refreshed inventory (``reports/m7/evren_run_inventory.json``, written by
``scripts/evren_inventory.py``), downloads one PyTorch checkpoint per planned run with a valid
model, plus the replicate jobs that serve only as a training-noise diagnostic, into
``<OPENINSPECT_DATA_DIR>/models/m7/``. Files are named by run id, never by the served file name,
and each one is verified: its size against the size EVREN registered for the model version, and the
job id inside its ``train_args`` against the inventory. Writes ``reports/m7/checkpoint_manifest.csv``
and ``reports/m7/final_run_manifest.{csv,json}``.

Credentials come from the environment only (``EVREN_MODEL_API_KEY``, else
``EVREN_PLATFORM_API_KEY``). The download endpoint returns a signed URL; it is used once and is never
printed or stored, and the key is only ever sent to the API host (redirects are not followed with
it). Nothing on EVREN is created, changed or deleted.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from evren_inventory import DEFAULT_API, PATH_KEYS, PHASE_KEYS, RUN_KEYS, UUID, read_checkpoint

REPO = Path(__file__).resolve().parents[1]
REPORTS = REPO / "reports" / "m7"
INVENTORY = REPORTS / "evren_run_inventory.json"
DOWNLOAD = re.compile(rf"^/models/versions/{UUID}/download$")
FORMAT = "pytorch"
Json = dict[str, Any]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A keyed request must not follow a redirect: the key would travel to the new host."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _get(url: str, headers: Mapping[str, str], *, follow: bool) -> tuple[int, bytes]:
    if not url.startswith("https://"):
        raise RuntimeError("only https downloads are allowed")
    handlers = [] if follow else [_NoRedirect()]
    opener = urllib.request.build_opener(*handlers)
    request = urllib.request.Request(url, headers=dict(headers), method="GET")  # noqa: S310
    try:
        with opener.open(request, timeout=300) as response:
            return int(response.status), bytes(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def download(api: str, key: str, version_id: str) -> bytes:
    path = f"/models/versions/{version_id}/download"
    if not DOWNLOAD.match(path):
        raise RuntimeError(f"{path} is not the model-version download endpoint")
    auth = {"X-API-Key": key} if key.startswith("evren_") else {"Authorization": f"Bearer {key}"}
    status, body = _get(
        f"{api}{path}?{urllib.parse.urlencode({'format': FORMAT})}",
        {**auth, "Accept": "application/json"},
        follow=False,
    )
    if status != 200:
        raise RuntimeError(f"download link for version ..{version_id[-8:]}: HTTP {status}")
    info = json.loads(body)
    info = info.get("data", info) if isinstance(info, dict) else {}
    url = str(info.get("download_url") or "")
    if not url:
        raise RuntimeError(f"no download link for version ..{version_id[-8:]}")
    target = urllib.parse.urlparse(urllib.parse.urljoin(api + "/", url))
    same_host = target.netloc == urllib.parse.urlparse(api).netloc
    status, blob = _get(target.geturl(), auth if same_host else {}, follow=not same_host)
    if status != 200:
        raise RuntimeError(f"downloading version ..{version_id[-8:]}: HTTP {status}")
    return blob


def effective_hash(args: Mapping[str, Any]) -> str:
    """SHA-256 of the effective training arguments without run-specific and phase-dependent keys."""
    kept = {k: v for k, v in args.items() if k not in RUN_KEYS | PATH_KEYS | PHASE_KEYS}
    return hashlib.sha256(json.dumps(kept, sort_keys=True).encode("utf-8")).hexdigest()


def requested_hash(requested: Mapping[str, Any]) -> str:
    kept = {k: v for k, v in requested.items() if k not in RUN_KEYS}
    return hashlib.sha256(json.dumps(kept, sort_keys=True).encode("utf-8")).hexdigest()


def targets(inventory: Mapping[str, Any]) -> list[tuple[str, Json, str]]:
    """(file stem, job, purpose) for every checkpoint to fetch."""
    jobs = {j["id"]: j for j in inventory["jobs"]}
    out: list[tuple[str, Json, str]] = []
    for run in inventory["expected_runs"]:
        if run["scientifically_usable"]:
            out.append((run["run_id"], jobs[run["job_id"]], "planned run"))
    planned = {run["job_id"] for run in inventory["expected_runs"]}
    for rep in inventory.get("replicates", []):
        for job_id in rep["jobs"]:
            job = jobs[job_id]
            if job_id not in planned and job.get("model_version_id"):
                stem = f"noise/{job['identity']}__{job_id[-8:]}"
                out.append((stem, job, "training-noise replicate (not in the estimator)"))
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--inventory", type=Path, default=INVENTORY)
    parser.add_argument("--data-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    data_dir = args.data_dir or Path(os.environ.get("OPENINSPECT_DATA_DIR", ""))
    if not str(data_dir) or not data_dir.is_dir():
        print("set OPENINSPECT_DATA_DIR or pass --data-dir", file=sys.stderr)
        return 2
    key = os.environ.get("EVREN_MODEL_API_KEY") or os.environ.get("EVREN_PLATFORM_API_KEY", "")
    if not key:
        print("no EVREN key in the environment", file=sys.stderr)
        return 2
    api = os.environ.get("EVREN_API_URL", DEFAULT_API).rstrip("/")
    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    folder = data_dir / "models" / "m7"
    sizes = {m["version_id"]: m["file_size_bytes"] for m in inventory["models"]}
    rows: list[Json] = []
    for stem, job, purpose in targets(inventory):
        path = folder / f"{stem}.pt"
        path.parent.mkdir(parents=True, exist_ok=True)
        vid = job["model_version_id"]
        if not path.is_file() or path.stat().st_size != sizes.get(vid):
            blob = download(api, key, vid)
            temporary = path.with_suffix(".part")
            temporary.write_bytes(blob)
            temporary.replace(path)
            print(f"downloaded {stem}.pt ({len(blob):,} bytes)")
        ckpt = read_checkpoint(path)
        problems = []
        if ckpt["bytes"] != sizes.get(vid):
            problems.append(f"size {ckpt['bytes']} != registered {sizes.get(vid)}")
        if ckpt["job_id"] != job["id"]:
            problems.append(f"train_args name job {ckpt['job_id']}, expected {job['id']}")
        if ckpt["train_args"].get("seed") != job["seed"]:
            problems.append("seed differs from the job")
        rows.append(
            {
                "file": f"{stem}.pt",
                "purpose": purpose,
                "job_id": job["id"],
                "model_version_id": vid,
                "dataset": job["dataset_name"],
                "seed": job["seed"],
                "bytes": ckpt["bytes"],
                "registered_bytes": sizes.get(vid),
                "sha256": ckpt["sha256"],
                "ultralytics_version": ckpt["ultralytics_version"],
                "saved_at": ckpt["date"],
                "effective_config_sha256": effective_hash(ckpt["train_args"]),
                "requested_config_sha256": requested_hash(job["requested"]),
                "best_epoch_metrics_match_evren": ckpt["train_metrics"].get("metrics/mAP50-95(B)")
                == job["val_mAP50_95"],
                "verified": not problems,
                "problems": "; ".join(problems),
                "_train_args": ckpt["train_args"],
            }
        )
    write_checkpoint_manifest(rows)
    write_final_manifest(inventory, rows, folder)
    bad = [r["file"] for r in rows if not r["verified"]]
    print(
        f"{len(rows)} checkpoints, {len(rows) - len(bad)} verified"
        + (f"; FAILED: {bad}" if bad else "")
    )
    return 1 if bad else 0


CHECKPOINT_FIELDS = (
    "file",
    "purpose",
    "job_id",
    "model_version_id",
    "dataset",
    "seed",
    "bytes",
    "registered_bytes",
    "sha256",
    "ultralytics_version",
    "saved_at",
    "effective_config_sha256",
    "requested_config_sha256",
    "best_epoch_metrics_match_evren",
    "verified",
    "problems",
)


def write_checkpoint_manifest(rows: Sequence[Json]) -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    with (REPORTS / "checkpoint_manifest.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CHECKPOINT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


FINAL_FIELDS = (
    "intended_run_name",
    "classification",
    "job_id",
    "run_name_on_evren",
    "dataset",
    "dataset_id",
    "dataset_version",
    "dataset_version_id",
    "seed",
    "model_id",
    "model_version_id",
    "epochs_completed",
    "best_epoch",
    "best_epoch_evren_field",
    "val_mAP50",
    "val_mAP50_95",
    "val_precision",
    "val_recall",
    "val_f1",
    "checkpoint_file",
    "checkpoint_sha256",
    "checkpoint_bytes",
    "checkpoint_verified",
    "effective_config_sha256",
    "requested_config_sha256",
    "history",
)


def write_final_manifest(inventory: Mapping[str, Any], rows: Sequence[Json], folder: Path) -> None:
    jobs = {j["id"]: j for j in inventory["jobs"]}
    by_file = {r["file"]: r for r in rows}
    records: list[Json] = []
    for run in inventory["expected_runs"]:
        job = jobs.get(run["job_id"] or "")
        ck = by_file.get(f"{run['run_id']}.pt")
        records.append(
            {
                "intended_run_name": run["run_id"],
                "classification": run["classification"],
                "job_id": run["job_id"],
                "run_name_on_evren": job["run_name"] if job else None,
                "dataset": run["dataset"],
                "dataset_id": job["dataset_id"] if job else None,
                "dataset_version": job["dataset_version_tag"] if job else None,
                "dataset_version_id": job["dataset_version_id"] if job else None,
                "seed": run["seed"],
                "model_id": run["model_id"],
                "model_version_id": run["model_version_id"],
                "epochs_completed": job["events"]["epochs_completed"] if job else None,
                "best_epoch": job["events"]["best_epoch_events"] if job else None,
                "best_epoch_evren_field": job["best_epoch_evren"] if job else None,
                "val_mAP50": job["val_mAP50"] if job else None,
                "val_mAP50_95": job["val_mAP50_95"] if job else None,
                "val_precision": job["val_precision"] if job else None,
                "val_recall": job["val_recall"] if job else None,
                "val_f1": job["val_f1"] if job else None,
                "checkpoint_file": f"{folder.name}/{ck['file']}" if ck else None,
                "checkpoint_sha256": ck["sha256"] if ck else None,
                "checkpoint_bytes": ck["bytes"] if ck else None,
                "checkpoint_verified": ck["verified"] if ck else False,
                "effective_config_sha256": ck["effective_config_sha256"] if ck else None,
                "requested_config_sha256": ck["requested_config_sha256"] if ck else None,
                "history": run["history"],
            }
        )
    hashes = {r["effective_config_sha256"] for r in records if r["effective_config_sha256"]}
    payload = {
        "frozen_from": "reports/m7/evren_run_inventory.json",
        "inventory_generated_at": inventory["generated_at"],
        "validation_scores_note": "EVREN's own scores on each run's validation split; not the M7 result",
        "best_epoch_note": "best_epoch is the event-stream epoch whose validation metrics EVREN reports; EVREN's own field is one higher except at the last epoch",
        "effective_config_note": "SHA-256 of the checkpoint's train_args without seed, paths and phase-dependent keys (mosaic, mixup, copy_paste, val)",
        "distinct_effective_configs": len(hashes),
        "runs": records,
        "replicates": [r for r in rows if r["purpose"] != "planned run"],
    }
    for r in payload["replicates"]:
        r.pop("_train_args", None)
    (REPORTS / "final_run_manifest.json").write_bytes(
        (json.dumps(payload, indent=1, ensure_ascii=False, default=str) + "\n").encode("utf-8")
    )
    with (REPORTS / "final_run_manifest.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FINAL_FIELDS)
        writer.writeheader()
        for rec in records:
            flat = dict(rec)
            flat["history"] = " | ".join(
                f"{h['job_id'][-8:]} {h['status']}: {h['role']}" for h in rec["history"]
            )
            writer.writerow(flat)


if __name__ == "__main__":
    sys.exit(main())
