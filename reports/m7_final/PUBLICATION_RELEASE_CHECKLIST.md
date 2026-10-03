# Publication release checklist (public-safe package)

Status 3 October 2026: **executed.** The private files were archived outside the repository, `.gitignore` was updated, the public files were scanned, committed, tagged and pushed (see the release commit and tag `research-m7-final`).

## 1. Secrets and identifiers

| check | result |
|---|---|
| EVREN API keys in any file to be committed | **none found**: scanned for the `evren_…` key pattern. `.env` is git-ignored; `.env.example` contains variable names only. |
| Signed download URLs | **none stored**: the download scripts use them once and never write them. |
| Full EVREN job / model / dataset-version UUIDs | present only in the **private** files listed in §3 |
| 8-character job-ID fragments | removed from public reports and scripts: replaced by run aliases (`C0-d1-s1-r1`, `-r2`) |
| Personal paths (`C:\Users\…`) | removed from all public scripts: runnable scripts use `OPENINSPECT_DATA_DIR`; provenance copies use `<REPO>`, `<SCRATCH>`, `<LOCAL>` placeholders |
| Account names or user metadata (`run_by_*` fields) | only in private inventory files |
| e-mail addresses | none in public files |

## 2. Public files (safe to commit)

**Paper**

- `paper/`: manuscript, section files, `CITATION_AUDIT.md`, `FINAL_REVIEWER_2_AUDIT.md`, `PORTFOLIO_SUMMARY.md`
- `paper/figures/`, `paper/tables/`, `paper/scripts/`
- `paper/arxiv/`: tex, bib, figures, README
- `paper/submission/`

**Final reports and analysis** (`reports/m7_final/`)

- the `FINAL_*.md` and `FINAL_*.csv` files, **except** `FINAL_RUN_INVENTORY.csv`
- `PUBLICATION_CONSISTENCY_AUDIT.md`, `PUBLICATION_RELEASE_CHECKLIST.md`, `FINAL_FREEZE_MANIFEST.md`
- `EVREN_SAYZEK_TECHNICAL_BRIEF_TR.md`, `OPENINSPECT_FINAL_ONE_PAGE_TR.md`
- `public/RUN_INVENTORY_PUBLIC.csv`, `public/CHECKPOINT_MANIFEST_PUBLIC.csv`
- `scripts/` (sanitised), `replication_summary.csv`, the figures, `analysis_meta.json`, `visual_category_gain_D0.csv`

**Independent review** (`reports/m7_independent_review/`)

- all reports; pre-replication reports carry a "superseded" banner
- `data/` (AI review labels and blinded keys; no personal data)
- `scripts/` (provenance copies with redacted paths)
- `figures/`

**Original M7 reports** (`reports/m7/`)

- `final_results.md` (with the superseded banner), `evaluation_protocol.md`, the result CSVs (`d0_seed_results.csv`, `probe_control_results.csv`, `bootstrap_results.csv`, `replication_results.csv`, `source_shift_results.csv`, `final_metrics.*`), `evren_api_audit.md` (endpoint audit; no identifiers), `figures/`

**Code and configuration**

- `scripts/m7_evaluate.py`, `scripts/m7_checkpoints.py`, `scripts/evren_inventory.py`: read-only tools; they contain the API host but no credentials
- `README.md` (new research section), `.env.example`, `pyproject.toml`

## 3. Private files (do NOT commit)

**Done:** all of them were moved to `C:\data\openinspect-private\m7-publication-freeze\` (34 files: the 29 operational files plus 2 logs and 3 superseded interim arrays, with the directory structure preserved and `SHA256SUMS` verified) and are excluded by `.gitignore`. Replicate job-ID fragments in public result files were replaced by the aliases r1/r2.

- `reports/m7/evren_run_inventory.{csv,json}`, `reports/m7/final_run_manifest.{csv,json}`, `reports/m7/checkpoint_manifest.csv`: full job, model and dataset-version IDs and user metadata
- `reports/m7/m7_expected_vs_actual.md`, `reports/m7/m7_config_consistency.md`: job-ID fragments
- `reports/m7_final/inventory_refresh/`, `reports/m7_final/inventory_after/`: raw inventories with IDs
- `reports/m7_final/FINAL_RUN_INVENTORY.csv`, `reports/m7_final/checkpoint_manifest_replication.csv`: IDs. Public equivalents are in `public/`.
- `reports/m7_final/LAUNCH_SHEET.md`: internal operations sheet with job-ID fragments
- `reports/m7_final/interim_pre_replication/`, `final_analysis.log`, `interim_pre_replication.log`: superseded intermediate outputs, private by default
- `reports/m7_final/scripts/fetch_replication_checkpoints.py` and `eval_replication.py`: no secrets, but they read the private inventory and manifest. Keep them private, or publish them while noting that they need the private files.

## 4. Checkpoint policy

- **Default: do not publish `.pt` weights.** Publish the hashes (`public/CHECKPOINT_MANIFEST_PUBLIC.csv`) and the retraining instructions.
- **Reasons:**
  - The reported numbers can be checked from the stored per-image predictions without the weights.
  - The weights were produced on a third-party platform under its terms of service, which have not been reviewed for redistribution.
  - Ultralytics YOLO11 is AGPL-3.0; distributing derived weights may carry obligations that have not been assessed.
  - About 25 files of 5.5 MB each add little value.
- **Never commit `.pt` files to git.** Weights live under `OPENINSPECT_DATA_DIR`, outside the repository.
- If weights are shared later, use a data archive (for example Zenodo) after a licence check, and verify them against the published SHA-256.

## 5. Release execution log

- [x] Private paths in §3 moved out of the repository and added to `.gitignore`; `*.pt`, `*.pth` and `*.onnx` are ignored.
- [x] Full git history (26 commits) and the staged tree scanned for API keys, tokens, signed URLs, passwords, personal paths and all 109 EVREN IDs plus their 8-character fragments: none found.
- [x] Committed and tagged (`research-m7-final`, annotated).
- [x] Local release checks: pytest 743 passed / 1 skipped (coverage 95.73%), `ruff check` and `ruff format --check` pass, mypy strict clean (166 files). The frozen research-analysis scripts are excluded from ruff and documented in `pyproject.toml`.
- [ ] Open item: extend the forbidden-claims test to `reports/m7_final/` and `paper/`.
