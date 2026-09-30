# Dependencies

Free and open-source only; no paid cloud service is required (brief §3). Add a dependency only when the milestone that needs it starts. Versions are pinned by `uv.lock` (created in M1).

**Licence column:** *verified* = checked against a primary source on 2026-09-30; otherwise it is the maintainers' published licence and will be machine-checked in CI (from M1) with `pip-licenses`, which will fail the build on any GPL/AGPL package in the core install.

| group | package | purpose | licence | milestone |
|---|---|---|---|---|
| runtime | Python 3.12 (dev machine: 3.12.10) | language | PSF | M1 |
| build | `hatchling` | build backend for `pyproject.toml` | MIT | M1 |
| core | `pydantic` ≥ 2 | manifest and record schemas | MIT | M1 |
| core | `PyYAML` (6.0.3 is installed) | read/write source manifests (`safe_load`) | MIT | M1 |
| core | `typer` | CLI (`source …`, `ingest …`, later `dedup`, …) | MIT | M1 |
| core | `httpx` | resumable, checksum-verified downloads (later the EVREN client) | BSD-3 (verified, installed metadata) | M2 |
| core | `defusedxml` | parse the VOC XML files of untrusted archives | PSF-2.0 (verified, installed metadata) | M2 |
| core | `pillow` (≥ 10.3) | image decode, integrity checks, metadata, dHash (crops later) | MIT-CMU, formerly HPND (verified, installed metadata) | M2 |
| data | `numpy`, `pandas`, `pyarrow` | tables, statistics, optional Parquet | BSD-3, BSD-3, Apache-2.0 | when first needed (M2 did not need them) |
| dedup | `imagehash` | 64-bit pHash | BSD-2 | M3 |
| ml | `torch` (installed 2.11.0, CPU build) | embeddings, local inference; CUDA build only for GPU smoke tests | BSD-3 | M3 |
| ml | `transformers` | DINOv2 (`facebook/dinov2-small`) | Apache-2.0; model card licence **apache-2.0 (verified)** | M3 |
| ml | `open_clip_torch` | alternative embeddings | MIT; **weights: check the licence of the chosen pretrained tag** | M3 |
| ml | `faiss-cpu` (or plain NumPy at 5k vectors) | nearest-neighbour search | MIT | M3 |
| ml | `scikit-learn`, `scipy` | out-of-fold classifiers, outlier scores, clustering | BSD-3 | M4 |
| eval | `pycocotools` or `torchmetrics` (decide in M8; test against a reference) | COCO-style mAP | BSD-2, Apache-2.0 | M8 |
| evren | `httpx` (already core) | API client; retry with backoff and the `.env` reader are in-house (`ingest/download.py`, `settings.py`), so `tenacity` and `python-dotenv` are not needed | BSD-3 | M8 |
| **optional extra `local-train`** | `ultralytics` (latest 8.4.168) | YOLO11 / RT-DETR for `LocalProvider` and smoke tests | **AGPL-3.0 (verified, PyPI metadata)** | M7 |
| optional | `cleanlab` | cross-check for the label audit; the audit itself is implemented in-house | **Apache-2.0 on `master` (verified)**; some earlier releases were reported as AGPL-3.0, so check the licence metadata of the exact version you pin | M4 |
| optional | `duckdb` | ad-hoc SQL over JSONL/CSV manifests | MIT | M3 |
| optional (backend) | `fastapi`, `uvicorn`, `sqlalchemy`, `psycopg`, PostgreSQL + `pgvector` | backend after the research result (brief §33) | MIT, BSD-3, MIT, LGPL-3.0, PostgreSQL licence | later |
| dev | `pytest`, `pytest-cov`, `hypothesis`, `ruff`, `mypy`, `types-PyYAML`, `types-defusedxml`, `pre-commit`, `pip-licenses`, `gitleaks` | tests, property tests, lint, types, hooks, licence and secret scans | MIT, MIT, MPL-2.0 (dev only), MIT, MIT, Apache-2.0, Apache-2.0, MIT, MIT, MIT | M1 |

## Policies

1. **AGPL isolation.** `ultralytics` is AGPL-3.0. It stays an optional extra (`pip install openinspect[local-train]`), is never vendored, and is never bundled into a released Docker image or artefact. The core install must not depend on any AGPL/GPL package (CI check). The README states this.
2. **Model weights are not code.** DINOv2 weights: Apache-2.0 (Hub metadata). Ultralytics pretrained weights follow Ultralytics' terms (AGPL-3.0 unless a separate licence applies). Check the licence shown for any model exported from EVREN before sharing it.
3. **Lock and audit.** `uv.lock` is committed; CI runs `pip-licenses` and fails on policy violations. A dependency added later must state its licence in this table in the same pull request.
4. **No cloud API** is a hard dependency. EVREN is optional at run time: without it the project runs through `LocalProvider`.
5. **YAGNI.** OpenCV, Polars, Docker Compose, PostgreSQL and pgvector are not needed for v0.1 and are added only if a milestone proves the need.

## Local environment notes (2026-09-30)

- PyTorch is a **CPU build** (`2.11.0+cpu`); `torch.cuda.is_available()` is `False`. GPU smoke tests need a CUDA build from the selector on pytorch.org.
- `ultralytics` is not installed; it is installed only for M7.
- The GPU has 4 GB VRAM: fine for YOLO11n smoke tests with a small batch, not for real training.
