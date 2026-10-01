# Changelog

All notable changes are recorded here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow PEP 440.

## [Unreleased]

### Added — M5.5: training readiness

- `openinspect readiness compute | report | check`.
  - `compute` (needs the data directory) rebuilds the committed release from its files and checks that A0, A1 and B re-derive exactly, builds the controlled designs and the B-natural folds, recomputes the release's components under DINOv2-small and DINOv2-base from the M3 caches, diagnoses the PCB-Defect giant component (scan and crop graphs; the 939 crops are embedded once and cached), places the 437 M4 findings against the release, runs the source identity probe, writes every package of the M7 plan to `<data>/exports/v0.1/` and validates it twice (with `--ultralytics-python`, the Ultralytics dataset checks in a separate environment; and `openinspect.exportcheck`), then decides the verdict by its rule. It writes `artifacts/m5_5/` (`readiness.json` and its tables), `manifests/experiments/v0.1/` and `reports/m5_5/`.
  - `check` (in CI, no data) re-derives the designs, the held-out folds, the label intersection, the probe and the base-built A1 from committed files, checks the purity of every held-out split and the identity of the common test and validation sets, that no input of M3 to M6 changed, and that the reports are what `readiness.json` renders; `report` re-renders the reports.
- Controlled designs C0/C1 (seeds 0, 1, 2): one common test set (probes exposed to their group-mates in C0, controls exposed in neither) and one validation set; training sets of equal size, source mix and (as far as replacements allow) boxes per class; roles of every item in `C-design<seed>-roles.csv`.
- B-natural folds next to the M5 split B, renamed B-strict in the documentation (its files are unchanged).
- `openinspect.exportcheck`: a YOLO package parser that imports nothing from `openinspect`; `scripts/validate_export_ultralytics.py` for the Ultralytics checks in a separate environment (Ultralytics stays outside the project).
- Reports: `TRAINING_READINESS.md` (verdict, blockers, limitations, the twelve questions), `controlled-design.md`, `representation-sensitivity.md`, `pcb-defect-component.md`, `release-label-quality.md`, `source-probe.md`, `export-validation.md`, `m7-plan.md` (not executed).
- CI runs `openinspect readiness check`.
- Decisions T39–T48.

### Added — M6: EVREN import smoke test

- `manifests/releases/v0.1/evren-smoke/observed.yaml`: the maintainer's observations in the EVREN UI, as text.
- `openinspect release smoke-verify`: compares every observation with the expectation committed before the upload and, with the data directory, with the ZIP; writes `artifacts/m6/evren-smoke-test.json` and `reports/m6/evren-smoke-test.md`. Verdict: PASS (13 of 13 comparisons match).
- `docs/EVREN.md`: YOLO Detection import, class import, split preservation for the tested package, version creation and freezing, and the Dataset Health panel are now OBSERVED; everything else keeps its status.
- Decisions T37–T38.

### Added — M5: release assembly, canonical splits, EVREN smoke package

- `openinspect release build | check | report | smoke | export`.
  - `build` assembles release v0.1 from the ingest records, the taxonomy and the M3 artifacts: content-defined global ids, the crop policy D7 for PCB-Defect, quotas (no source above 40%), a seeded class-stratified sample, the splits A0, A1 and B per source, their measurements and the invariants I1 to I9; it writes the images to `<data>/release/v0.1/images/`, and to the repository `manifests/releases/v0.1/{release.json, items.parquet, annotations.parquet, excluded.parquet}`, `manifests/splits/v0.1/*.csv` with `.meta.json`, and `reports/m5/release.md`.
  - `check` re-verifies the committed release from its files (hashes, I1 to I5, I7 to I9) and runs in CI; `report` re-renders the report; `smoke` writes the EVREN smoke-test ZIP (YOLO Detection, 10/5/5 known A1 items) to `<data>/exports/v0.1/` and commits its SHA-256 and the expected split of every item; `export` writes the full package of one scheme.
- `configs/release.yaml`: version, seed, size range, share limit, negatives, crop policy per source, split ratios, smoke counts.
- Release v0.1: 4,420 images, 5,297 boxes (DsPCBSD+ 1,768, PCB-IND 1,713, PCB-Defect 939 crops); A1 crosses 0 supplied groups; A1 holds PCB-Defect in train and val only (one constraint group of 859 of 939 crops).
- Decisions T32–T36.

### Added — M4: taxonomy and label quality

- `configs/taxonomy.yaml`: every source label mapped once to a normalized class with a status (EXACT, COMPATIBLE, AMBIGUOUS, SOURCE_SPECIFIC, REJECTED) and quoted evidence; a two-level hierarchy; the candidate merges that were examined and not made; the label-quality rules. Explained in [docs/TAXONOMY.md](docs/TAXONOMY.md).
- `openinspect taxonomy check | audit | report`: `check` verifies the mapping against the source manifests and the ingest reports (in CI, no data); `audit` writes `artifacts/m4/taxonomy-map.parquet` (one row per box, original and normalized label side by side), `artifacts/m4/review-required.csv` (status `REVIEW_REQUIRED`, decision columns empty), `artifacts/m4/audit.json` and `reports/m4/` (taxonomy mapping, class overlap, label quality); `report` re-renders them.
- Benchmark classes (reached by every source with EXACT or COMPATIBLE): `short`, `open`, `mouse_bite`, `spurious_copper`.
- `openinspect.validation`: the human-validation status is read from the M3 review queue; every M3 report now states "Human validation: NOT PERFORMED, reviewed pairs 0 / 300" and the limitation of the similarity findings (T29). No M3 number changed.
- Decisions T29–T31.

### Added — M3: similarity and leakage audit, dataset assurance report

- `openinspect dedup features | synthetic | analyze | review | report | run`.
  - `features` decodes every image once, checks its SHA-256 against the ingest record, and caches a 64-bit pHash and a DINOv2 embedding (L2-normalised CLS token, preprocessing `v1`, backend `cpu-fp32`); the cache key is image SHA-256, model and pinned revision, preprocessing version and backend, so an interrupted run resumes and nothing is embedded twice.
  - `synthetic` embeds seeded, mildly transformed copies of 100 images per source (11 transforms, protocol section 5).
  - `analyze` needs no model: calibration against the sources' own keys (proxy metadata), the frozen threshold rule, exact cosine search, per-source similarity graphs with a percolation sweep, split leakage per level, a random-split baseline (1,000 permutations), a group-aware split whose crossings are measured, key overlap, cohesion, chaining and stability, a hash audit (SHA-256, pHash, dHash), candidate pairs with machine categories, the synthetic recall achieved at the final threshold, a both-sides bootstrap check, and with `--robustness-model` a second representation compared by conclusions and partition agreement.
  - `review` writes a local HTML contact sheet of a seeded review queue of about 300 pairs (stratified by source, band, split relation and metadata relation) plus a seeded sample of components; `report` re-renders the reports from `artifacts/m3/audit.json`; `run` does everything, reusing the caches.
- `openinspect.assurance`: a dimensional dataset assurance report (provenance, licence evidence, archive integrity, exact duplicates, visual similarity leakage, group split integrity, independent source validation, source diversity, cross-source overlap) with explicit rules and evidence, and no scalar score.
- The protocol ([docs/M3_PROTOCOL.md](docs/M3_PROTOCOL.md)) was committed before any number was computed and is unchanged (a test checks its SHA-256); corrections, the eight points of an independent red-team review, and implementation notes are in [docs/M3_PROTOCOL_AMENDMENT.md](docs/M3_PROTOCOL_AMENDMENT.md), each with the previous rule, the issue, the correction and the effect on interpretation.
- Reports in `reports/m3/`: similarity summary, threshold calibration, split leakage, source comparison, representation robustness, dataset assurance, limitations, performance, with SVG figures. Artifacts in `artifacts/m3/`: `audit.json`, `thresholds.json`, `synthetic-recall.json`, `duplicate-pairs.parquet`, `leakage-groups.parquet`, `review-candidates.csv` (tracked) and `nearest-neighbors.parquet` (regenerable, listed by SHA-256).
- The core uses generic keys only (`group_id`, `subgroup_id`, `acquisition_id`); `configs/dedup.yaml` maps each source onto them, declares its calibration pools, and pins DINOv2-small and DINOv2-base by revision and weights SHA-256.
- Position: a reproducible dataset and benchmark assurance preflight; prior art (FiftyOne Brain, Cleanlab, imagededup) acknowledged in the README; A0 − B is not a leakage measure (SPEC 7.6).
- Dependencies: `numpy` and `pyarrow` in the core; `torch` (CPU-only index) and `transformers` in the optional extra `embeddings`.
- Decisions T15–T28 in [docs/DECISIONS.md](docs/DECISIONS.md).
- Integration tests check the committed reports against `audit.json`, the tracked artifacts against their digests, the thresholds against the rule, and the frozen protocol against its hash.


### Added — licence

- `LICENSE`: Apache-2.0 for the code (decision D3, chosen by the maintainer); `pyproject.toml` declares it.

### Added — M2: ingest

- `openinspect ingest download | extract | inspect | run | report`.
  - `download` fetches each accepted archive from its manifest URL, resumes interrupted transfers, retries with backoff, and keeps a file only if its size and the repository's checksum (MD5 or SHA-256) match; it computes the SHA-256 and writes `download_date` (first download only) and `archive_sha256` into the manifest.
  - `extract` checks the CRC-32 of every zip member and extracts safely: no path traversal, absolute paths, reserved Windows names, case-insensitive collisions or symlinks; member-count and size limits; a `.partial` directory that is renamed on success; SHA-256 of every file.
  - `inspect` prints the extracted file tree; `run` does all of the above, reads the annotations, decodes every image and writes records and reports; `report` rebuilds the Markdown report.
- One adapter per source, written after looking at the real archives: `dspcbsd-plus` (COCO canonical, YOLO cross-check), `pcb-ind` (YOLO canonical, COCO and VOC cross-check), `pcb-defect` (COCO). Orphan images, orphan annotations, degenerate boxes and disagreements between formats are reported as anomalies, not repaired silently.
- Image and annotation records (SHA-256, size, format, EXIF orientation, 64-bit dHash, original split, group key, labels) as JSONL under the data directory. In git: `manifests/ingest/<slug>/report.json` and `download.json`, `manifests/ingest/cross_source.json`, and `reports/m2-ingest-report.md` (images, annotations, classes, original splits, grouping key, anomalies and adapter status per source).
- Reconciliation of each manifest with its archive (ingest gate G7): counts, class counts, sizes and splits are recomputed and compared. The three manifests now carry the measured values (class counts, image sizes, group keys, weaknesses).
- Exact-duplicate check (SHA-256) inside each source and across sources: none found.
- `openinspect.settings`: the data directory comes from `--data-dir`, `OPENINSPECT_DATA_DIR` or `.env`; a directory inside the repository or OneDrive is refused; free-space check.
- Dependencies: `httpx`, `pillow`, `defusedxml`; dev: `types-defusedxml`.
- 367 tests (unit tests on synthetic archives with the real layouts, plus integration tests that check the committed reports against the manifests), 99% coverage.
- Decisions T8–T14 in [docs/DECISIONS.md](docs/DECISIONS.md).

### Added — M1: source registry

- `openinspect source add | list | show | validate` (Typer CLI, also `python -m openinspect`).
  - `add` registers a pending or rejected source from flags, or any complete manifest with `--from-file`; it refuses duplicate slugs (`--force` replaces only the file named after the slug) and cannot create an `accepted` source from flags.
  - `list` and `show` support `--json`; `list` can filter by `--status`.
  - `validate` checks schema, licence allowlist, evidence hashes against `manifests/evidence/SHA256SUMS.txt`, slug/file consistency and duplicate slugs; `--release public` fails for accepted sources whose redistribution or derivative-work answer is not `allowed`; `--strict` turns warnings into errors; exit code 1 on failure.
- Pydantic v2 schema of the source manifest with status rules (two tiers: accepted = admitted for internal use; public release needs redistribution and derivative work allowed).
- `configs/licences.yaml`: allowlist CC0-1.0 and CC-BY-4.0; NC, ND and SA terms are refused with an explanation.
- 161 tests (unit and integration), `ruff`, `mypy --strict`, 98% coverage.
- GitHub Actions: lint, type-check, tests (Ubuntu and Windows), manifest validation; actions pinned to commit SHAs.
- `README.md`, `SECURITY.md`.

### Added — M0: specification

- Technical specification, scope, repository structure, dependency list, dataset intake format, licence acceptance checklist, definition of done, decision log, EVREN facts and unknowns (`docs/`).
- Source manifests: `dspcbsd-plus`, `pcb-ind`, `pcb-defect` accepted (CC BY 4.0); `deeppcb` rejected (README limits use to research, LICENSE file says MIT).
- Licence evidence from the repository records, DataCite and Crossref, archived and hashed (`manifests/evidence/`); `scripts/hash_evidence.py` regenerates the hash list.
