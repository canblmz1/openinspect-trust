# OpenInspect-Trust — Technical Specification

| | |
|---|---|
| Status | **Accepted** on 2026-09-30 under the maintainer's autonomous-execution directive (decisions: [DECISIONS](DECISIONS.md)); open: D3, the code licence |
| Date | 2026-09-30 |
| Spec version | 0.1.0 |
| Requirements source | the *Master Build Prompt*, cited below as "brief §N" |

Companion documents: [REPO_STRUCTURE](REPO_STRUCTURE.md) · [DEPENDENCIES](DEPENDENCIES.md) · [DATASET_INTAKE](DATASET_INTAKE.md) · [LICENCE_CHECKLIST](LICENCE_CHECKLIST.md) · [DEFINITION_OF_DONE](DEFINITION_OF_DONE.md) · [DECISIONS](DECISIONS.md) · [EVREN](EVREN.md) · [LICENSE_MATRIX](../LICENSE_MATRIX.md)

## 1. Purpose and non-goals

OpenInspect-Trust measures whether an industrial vision benchmark actually generalizes beyond the sources it was built from. It assembles a small, licence-clean, provenance-complete, duplicate-audited benchmark from open datasets and compares conventional random splits with source-held-out evaluation.

Principle: **more trustworthy data, not more data.**

Non-goals for v0.1:

- Re-implementing what EVREN already provides (dataset management, annotation, training, registry): brief §4.
- Automating EVREN dataset upload, versioning or training. Only the authenticated inference API is verified (brief §5); everything else is done in the EVREN UI.
- A web UI or backend before there is a research result (brief §33).
- State-of-the-art accuracy, or any claim about "industrial vision" beyond the PCB domain (§11, R9).

## 2. Research questions and hypotheses (brief §6–7)

| id | statement | measured by | supported when |
|---|---|---|---|
| RQ1 | Do random splits overestimate defect-detection performance versus source-held-out evaluation? | | |
| H1 | The random-split score is substantially higher than the external-source score. | Generalization gap GG = score(random) − score(source-held-out) for mAP50, mAP50-95 and F1, per held-out source and pooled, with 95% CI (§7.7) | lower CI bound of GG > 0 for at least 2 of the 3 held-out sources and pooled |
| RQ2 | How much do exact duplicates, near-duplicates and source leakage distort scores? | gap decomposition (§7.6): leakage effect = A0 − A1, residual source shift = A1 − B | |
| H2 | Cleaning lowers the random-split score but makes it a more reliable predictor of external performance. | A0 − A1 > 0 with CI excluding 0, and abs(A1 − B) < abs(A0 − B) | both hold |
| RQ3 | Does data-centric cleaning help cross-source generalization more than a bigger model? | | |
| H3 | Clean + YOLO11n approaches or beats raw + YOLO11m on the held-out source. | Δ = mAP50(n, clean) − mAP50(m, raw), paired bootstrap | "approaches": lower CI bound > −δ (default δ = 0.02, D10); "beats": lower CI bound > 0 |
| H4 | The label-quality audit reduces cross-domain false positives and false negatives. | FP and FN counts at the validation-chosen F1-optimal confidence, audited vs original labels, on external sources | both drop with paired-bootstrap CI excluding 0, or F1 improves |

**Analysis plan freeze.** This section, §7.6–7.7 and §8 are frozen with a git tag `analysis-plan-v0.1` before any result on an external test set is looked at. Deviations are logged in `experiments/DEVIATIONS.md`. A refuted hypothesis is a result and is reported as such.

## 3. v0.1 scope (brief §8)

| target | passes when | verified by |
|---|---|---|
| 3 independent source datasets | 3 sources `accepted` (admission gates G1–G6, G9) and the ingest gates G7, G8 passed at M2 | `openinspect source validate`, ingest report |
| 2,000–5,000 images | release count in range; sampling deterministic and documented (seed; no source above 40% of the release, 60% in the two-source fallback) | release stats |
| 3–5 normalized classes | taxonomy derived from real source labels (§7.4) | `taxonomy/mapping.csv` |
| 100% provenance | every image and annotation row has all required provenance fields | validator in CI |
| 0 exact duplicates | no repeated SHA-256 in the clean release | dedup report |
| near-duplicate report | pHash + embedding candidates, calibrated thresholds, human decisions | `reports/` |
| random and source-aware splits | A0, A1, B (leave-one-source-out) generated, leakage tests green | CI |
| YOLO11n baseline on EVREN | run records for E1–E3 | `benchmarks/` |

Out of scope for v0.1: more than three sources, FastAPI backend, pgvector, automation of EVREN upload/training, RT-DETR (added after the pipeline is validated, brief §28), segmentation or classification tasks.

## 4. Domain and candidate sources

**Domain: PCB surface-defect detection with bounding boxes.** In the 2026-09-30 screening it was the only domain where three independent, box-annotated datasets with a verifiable open licence were found. Steel, concrete/bridge and road-damage candidates fell out on licence, annotation type or provenance ([LICENSE_MATRIX](../LICENSE_MATRIX.md)).

| slug | what | images / boxes | acquisition | licence |
|---|---|---|---|---|
| `dspcbsd-plus` | DsPCBSD+ (Sci Data 2024), 9 classes | 10,259 / 20,276 | factory AOI, etch stage, 226×226 JPG crops, pre-processed | CC BY 4.0 |
| `pcb-ind` | PCB-IND v4 (Sci Data 2026), 8 classes | 4,789 / 5,932 | factory AOI, outer-layer etch stage, 300×300 ROI patches around AOI-reported anomalies | CC BY 4.0 |
| `pcb-defect` | PCB-Defect (Data in Brief, vol. 64), 6 classes | 230 / 1,704 | lab: etched single-layer FR4 boards, flatbed scan at 1600 dpi, 800×600 to 6000×4000 px, engineered defects | CC BY 4.0 |

All three: licence read from the repository record and confirmed by the DOI registry (DataCite) on 2026-09-30; status `accepted`, evidence archived and hashed. Nothing is downloaded before Milestone 2, and the ingest gates G7 and G8 still have to pass. `deeppcb` is rejected (DO NOT USE).

**Source-shift spectrum.** `dspcbsd-plus` and `pcb-ind` come from different producers (no shared authors or institutions) but the same modality, so holding out one of them mostly measures factory/device shift. Holding out `pcb-defect` measures lab-to-factory shift. Results are reported per source and never averaged without the per-source rows.

**Candidate class core (a hypothesis, not a decision; brief §18).** By name and meaning, the labels shared by all three sources are open, short, mouse-bite and spurious copper; `spur` is shared by two and would extend to a third if `copper_burr` (PCB-IND) is judged equivalent by visual review. The normalized taxonomy is built from the real files in M4; this paragraph only shows that "3–5 classes" is realistic.

## 5. Architecture

```
open datasets ─► source add / validate ............. manifests/sources/*.yaml          [M1]
      │
      ▼
ingest: download → verify → SHA-256 → integrity → metadata → normalise → provenance     [M2]
      │
      ▼
image records + annotation records (JSONL) = single source of truth
      ├─► dedup: exact (SHA-256) → pHash → embeddings → groups → human review          [M3]
      ├─► taxonomy: original → normalized (mapping.csv, human-reviewed)                [M4]
      ├─► audit: label-quality signals → review queue (a human decides)                [M4]
      └─► split: A0 random · A1 group-aware random · B source-held-out (LOSO) + tests  [M5]
            │
            ▼
      export YOLO/COCO ZIP ─► maintainer, in the EVREN UI: v0.1-raw, v0.1-clean (frozen) [M6]
            │
            ▼
      training on EVREN (UI) ─► model ─► export weights / inference API
            │
            ▼
      benchmark runner ─► InferenceProvider {EvrenProvider, LocalProvider}
                          ─► predictions ─► local evaluator ─► metrics ─► reports/       [M7–M9]
```

**EVREN boundary**

| activity | where | automated here? |
|---|---|---|
| dataset import, versioning, freezing, training, experiments, registry | EVREN UI | no (APIs not verified) |
| inference | EVREN model API (Bearer token) | yes (verified) |
| model export | EVREN UI | no; the exported weights feed `LocalProvider` |
| provenance, dedup, audit, splits, leakage tests, evaluation | this repository | yes |

EVREN facts and unknowns: [EVREN](EVREN.md). A UI feature is not an API: no dataset-create, upload, version, training or experiment endpoint is assumed.

**Provider interface (brief §32).** `InferenceProvider.predict(image_path) -> list[Detection]` with `Detection = (class_name, confidence, x_min, y_min, x_max, y_max)` in pixels of the image sent. `EvrenProvider` calls the API; `LocalProvider` runs exported weights (Ultralytics, optional extra). The evaluator is provider-independent, and **headline metrics are computed only by our evaluator from raw predictions**, never copied from a platform dashboard. A parity check on a 50-image sample compares the two providers.

**EVREN client (brief §30).** `src/openinspect/evren/client.py`: reads `EVREN_API_KEY` and `EVREN_MODEL_ENDPOINT` from the environment; explicit timeout; retry with exponential backoff and jitter on timeouts, 429 and 5xx (never on other 4xx); structured errors (`EvrenAuthError`, `EvrenRateLimitError`, `EvrenServerError`, `EvrenTimeoutError`, `EvrenResponseError`); the token is never logged or written to a run record. Documented inference parameters are model/version, confidence threshold, IoU threshold and JPEG quality; `max_det` is unknown and is not used. Images are sent at the highest allowed JPEG quality.

**Storage.** YAML for source manifests; JSONL/CSV for records, dedup groups, mappings and splits (small, diffable, versioned in git). Images, archives and embeddings live outside git under `OPENINSPECT_DATA_DIR`. DuckDB may query the JSONL/CSV files; embeddings are `.npy` with an in-memory exact search (5k vectors: FAISS flat or NumPy); pgvector is deferred (brief §15).

## 6. Data contracts

Deviations from the brief are marked **[dev]** and listed in D5.

### 6.1 Source manifest
[`manifests/sources/_template.yaml`](../manifests/sources/_template.yaml). Validation rules (M1, decision T4): `accepted` admits a source for download and internal use and requires an allowlisted licence, `licence_url`, all four rights answers, `verified_on`, at least one archived and hashed evidence entry, `attribution_text` when attribution is required, `official_url`, creators, version, `is_original_upload: true` and a complete `decision` block whose `status` matches. Public release additionally needs `redistribution` and `derivative_work` = `allowed`; an `unclear` answer blocks it. `rejected` requires `decision.reason`.

### 6.2 Image record (one JSONL line per image)

| field | notes |
|---|---|
| `id` | `OI_%06d`, assigned once; order = sort by (`source_dataset`, `source_item_id`) so it is reproducible |
| `source_dataset` | slug of a registry entry |
| `source_item_id` | POSIX path inside the source archive |
| `source_url` | record or archive URL (per-item URL when one exists) |
| `source_license` | SPDX id copied from the manifest |
| `original_labels` **[dev]** | sorted unique labels of the image's boxes (the brief has a singular `original_label`; detection images carry several) |
| `normalized_labels` **[dev]** | same after mapping; empty until M4 |
| `sha256` | hash of the file **as shipped in the release**; leakage tests compare this |
| `sha256_source` **[dev]** | hash of the original upstream file (equal to `sha256` when unmodified) |
| `sha256_pixels` | optional: hash of the decoded pixel array (catches container/metadata-only differences) |
| `phash` | 64-bit perceptual hash, hex |
| `split` | split in the default scheme; canonical assignments live in split files (§6.6) |
| `review_status` | `unreviewed` / `flagged` / `approved` / `excluded` |
| `source_group_id` **[dev]** | board, batch or parent-image key; needed for the "grouped source object" leakage test (brief §36) |
| `parent_id`, `crop_xyxy` **[dev]** | provenance of crops and tiles (brief §12 normalisation, "original info is never lost") |
| `width`, `height`, `format`, `bytes`, `exif_orientation` | metadata extraction (brief §12) |
| `dup_group_id` | link to a duplicate group |
| `selected`, `exclusion_reason` | sampling, dedup and taxonomy decisions are recorded, never silently deleted |

### 6.3 Annotation record (one line per box) **[dev]**
`ann_id`, `image_id`, `source_ann_id`, `original_label`, `normalized_label` (null until mapped), `bbox_xyxy` (release-image pixels), `bbox_source` (original coordinates and format), `mapping_status`, `review_status`, `review_note`.

### 6.4 Duplicate group (brief §16)
`group_id` (`DUP-019`), `items` (image ids), `similarity`, `type` (`exact` / `near_duplicate` / `group_overlap`), `method` (`sha256` / `phash` / `embedding`), `cross_source` (bool), `decision` (`review` / `keep_one` / `keep_all_same_split` / `not_duplicate`), `keep_id`, `decided_by`, `decided_on`. Only exact duplicates may be auto-decided; everything else is `review` until a human decides.

### 6.5 Taxonomy mapping (brief §17)
`taxonomy/mapping.csv` with columns `source_dataset, original_label, normalized_label, confidence, reason, review_status`. `confidence` is `high` / `medium` / `low`. Only `review_status = approved` rows apply to a release.

### 6.6 Split files
`manifests/splits/<scheme>__seed<N>.csv` (`id,split`) plus `.meta.json` (scheme, seed, hash of the image-record file, generator version, counts, SHA-256 of the CSV).

### 6.7 Run record
`benchmarks/runs/<run_id>/run.json`: experiment id, model, provider, EVREN dataset version id and the SHA-256 of the exact local ZIP that was uploaded, split scheme, seed, hyper-parameters, git commit, software versions, hardware, metric summary, SHA-256 of `predictions.jsonl`.

## 7. Methods

### 7.1 Ingestion and normalisation (brief §12)
Download → source validation → SHA-256 manifest → image integrity check → metadata extraction → format normalisation → provenance assignment. Every step writes an auditable artefact; a failing step stops the source instead of skipping files.

- Integrity: the image decodes fully, size > 0, dimensions plausible; **EXIF orientation is recorded and must be 1** (otherwise box coordinates may not match the pixels other tools show).
- Normalisation changes no pixels except cropping/tiling, which is recorded through `parent_id` and `crop_xyxy`. Images used as-is keep their bytes. Crops taken from JPEG parents are saved losslessly to avoid a second compression.
- **Scale and crop policy (D7).** Native sizes differ by orders of magnitude (226², 300², up to 6000×4000), while the nominal pixel pitch is similar (about 6–16 µm/px). Recommended policy: keep native resolution; cut large images (`pcb-defect`) into ROI crops of about 300×300 around annotations, mimicking how the AOI sets were made. The policy is part of the benchmark definition, fixed in M2, with a sensitivity check at a second crop size if budget allows.

### 7.2 Exact duplicates (brief §13)
SHA-256 of file bytes, and optionally of decoded pixels, computed **before** anything is uploaded to EVREN and **across** sources. Within a source the first item by sorted `source_item_id` is kept; the rest get `excluded: exact_duplicate`. A duplicate pair with conflicting labels is logged as a label-noise candidate. A cross-source exact duplicate means one source contains the other's images: it is a provenance finding (independence and licence), not just a cleaning step.

### 7.3 Near-duplicates (brief §14)
Stage A: 64-bit pHash, Hamming distance. Stage B: L2-normalised DINOv2-small embeddings (`facebook/dinov2-small`, Apache-2.0, 22M parameters, feasible on CPU), with OpenCLIP as a comparison; exact nearest-neighbour search. A pair is a candidate if the pHash distance ≤ h **or** cosine similarity ≥ τ. Candidate pairs form groups by connected components.

**Calibration (no arbitrary threshold).** Build a calibration set from (i) synthetic positives made by controlled transforms of random images (JPEG re-encode, ±10–25% resize, ≤10% shift/crop, brightness/contrast jitter), (ii) about 300 real candidate pairs sampled evenly across similarity bins and labelled by the maintainer as same-scene or different, (iii) hard negatives: nearest neighbours from different boards (PCB traces are repetitive, so structural similarity is high). Pick h and τ that maximise F2 at precision ≥ 0.9 on the human-labelled pairs, report the PR curves, and commit the labelled pairs to `benchmarks/dedup_calibration/`. The PCB-IND authors used pHash ≤ 3 as duplicate and 4–5 as distinct within a batch: a prior to compare with, not a rule.

### 7.4 Taxonomy (brief §17–18)
Two levels: original labels are never changed; `normalized_label` is assigned through `mapping.csv`. Procedure: extract labels and counts from the files (M2), draft mappings with reasons, review visually, freeze the mapping with a git tag before any training. A hierarchy (e.g. DEFECT → …) is added only if the data supports it.

**Unmapped labels.** Default: exclude the whole image (`excluded: unmapped_class`) and report how many were lost. Dropping only the box would silently turn a real defect into a "false positive" during training and evaluation. An `other` class is an alternative decided in M4.

### 7.5 Label-quality audit (brief §19)
Signals: S1 nearest-neighbour label disagreement on box-crop embeddings; S2 out-of-fold classifier disagreement (two model types); S3 detector disagreement (predicted vs ground-truth boxes at IoU ≥ 0.5: class mismatch, missed box, confident extra box); S4 embedding outliers; S5 duplicate pairs with conflicting labels. An item becomes `REVIEW_REQUIRED` when at least two independent signals agree on another label. **Models never change a label.** The queue is a file; the reviewer decides `keep` / `relabel:<class>` / `drop_box` / `add_box` / `ambiguous`; every decision is logged with reviewer and time. Corrections live only in `v0.1-clean`. Test-label corrections are evaluated separately (original-label test vs audited-label test). To estimate the audit's recall, a random sample of about 100 *unflagged* items is reviewed too.

### 7.6 Splits (brief §20–22)

| scheme | how | purpose |
|---|---|---|
| **A0** random | 70/20/10, stratified by class presence, on the *raw* pool | the conventional benchmark |
| **A1** group-aware random | same ratios on the *clean* pool; duplicate groups and `source_group_id` never straddle splits | removes leakage but keeps sources mixed |
| **B** source-held-out | train on K−1 sources, test on the held-out source; validation is 10–15% of the training sources, group-aware; run for every source (leave-one-source-out) | the real generalization test |

Gap decomposition: total = A0 − B, leakage effect = A0 − A1, residual source shift = A1 − B.
Confounds to report: training-set sizes differ (A0 is larger than a B fold; the clean pool is smaller than raw). Optional ablation: subsample A0 training to the B fold size.
**Paired comparison for H1:** evaluate the A0 model on the part of the A0 test set that belongs to source s, and evaluate the B fold that held out s on *the same images*.
No hyper-parameter tuning or checkpoint selection on a held-out source; checkpoints are chosen on the validation split of the training sources.

**Invariants** (tests, brief §35–36):

| id | invariant |
|---|---|
| I1 | for every B fold: set of train sources ∩ set of test sources = ∅ |
| I2 | no `sha256` shared between train and test in any scheme |
| I3 | no `id` or (`source_dataset`, `source_item_id`) overlap between splits |
| I4 | in A1 and B: no `source_group_id` shared between train and test (in A0 overlap is expected and measured) |
| I5 | near-duplicate train/test pairs are counted per scheme and reported; must be 0 for A1 and B |
| I6 | the same seed and record-file hash produce the same split file hash |
| I7 | every released row has non-empty `source_dataset`, `source_item_id`, `source_url`, `source_license`, `sha256_source` |
| I8 | every `source_license` is on the allowlist |
| I9 | every released `normalized_label` comes from an `approved` mapping row |
| I10 | the exported ZIP's file hashes equal the manifest hashes |

### 7.7 Metrics and evaluator (brief §29)
Precision, recall and F1 at the confidence that maximises F1 on the validation split (frozen before the test set is touched); mAP50, mAP50-95, per-class AP with COCO-style 101-point interpolation over all detections down to conf 0.001 (max_det 300, NMS IoU 0.7, the usual Ultralytics validation settings, for `LocalProvider`; the EVREN API's `max_det` is unknown); GG as defined in §2. Uncertainty: bootstrap with 1,000 resamples of images (cluster bootstrap by `source_group_id` where groups exist); paired differences use the same resamples. The evaluator is cross-checked against a reference implementation on a fixture within a small tolerance.

### 7.8 Release versions (brief §22–24)
The EVREN dataset is named `OpenInspect-Trust v0.1` (VISION modality) and frozen in two versions:

- **`v0.1-raw`**: a deterministic, seeded, class-stratified sample (cap 5,000 images) of the ingested sources after integrity checks and taxonomy mapping. **No deduplication and no label audit**, so it carries the dirt the experiments measure.
- **`v0.1-clean`**: `v0.1-raw` minus excluded items (exact duplicates, near-duplicates chosen by review, unmappable images), with audited label corrections applied to training data. Every clean id is also a raw id (clean ⊂ raw), so the two versions differ only by the cleaning.

The release count ranges (§3) apply to both. A public release additionally needs the release checklist in [LICENCE_CHECKLIST](LICENCE_CHECKLIST.md).

## 8. Experiments (brief §25–28)

Hyper-parameters are fixed per experiment in `experiments/*.yaml` and identical across raw/clean and across splits; only the data differs. Image size is chosen in the M7 smoke test (patches are ≤ 300 px, so 320 may cost less than 640 without losing information) and then frozen.

| id | question | runs (YOLO11n unless noted) |
|---|---|---|
| E1 cleaning effect | raw vs clean, same model and hyper-parameters | B-raw vs B-clean (3 folds each); A0-raw vs A1-clean. External sets are scored in their clean form for both models; raw form is secondary. |
| E2 random vs source-aware | GG and its decomposition | A0-raw, A1-clean, B-raw (3 folds) |
| E3 data vs capacity | raw + YOLO11m vs clean + YOLO11n | YOLO11m on B-raw (3 folds) against YOLO11n on B-clean |
| E4 model family | are results specific to YOLO? | RT-DETR on A0-raw, B-raw, B-clean, after E1–E3 work |

Training-run budget: per seed, 8 YOLO11n runs (E1/E2) + 3 YOLO11m runs (E3) = 11; three seeds = 33; plus 7 RT-DETR runs (one seed) = **≈ 40 EVREN runs**. Minimal variant with one seed: **≈ 18 runs**. Cost of one run on the lowest tier is `hours × 15 CR` (× 1.5 with priority; see [EVREN](EVREN.md)); the duration of a YOLO11n run is measured in the M7 smoke test, which never uses priority.

## 9. Compute and environment

Observed on 2026-09-30: Windows 11 Home, Python 3.12.10, git 2.53, Docker 29.3.1, uv 0.12.0, RTX 3050 Ti Laptop GPU with 4 GB VRAM, PyTorch 2.11.0 **CPU-only build** installed, C: is the only drive, with about 40 GB free of 476 GB (92% used), and the project folder sits inside OneDrive.

- Ingestion, dedup and embeddings run on CPU (about 5k small images with DINOv2-small).
- The local GPU is for smoke tests only (YOLO11n, tiny subset, few epochs, small batch) and needs a CUDA build of PyTorch. All real training happens on EVREN.
- **OneDrive:** synced folders risk sync conflicts, locked files and quota use. Decision D6: the repository stays where it is (risk recorded); raw data goes outside OneDrive and outside the repository under `OPENINSPECT_DATA_DIR` (suggested `C:\data\openinspect`), and so does the virtual environment (`UV_PROJECT_ENVIRONMENT`). Moving the repository to `C:\dev\openinspect-trust` removes the risk.
- Disk budget: keep total data under about 10 GB.

## 10. Reproducibility, security, quality gates

- `uv` with a committed lockfile; seeds recorded; deterministic ordering everywhere; every run writes a run record (§6.7); results are never overwritten.
- Secrets only in `.env` (git-ignored); `.env.example` stays empty; the client never logs tokens; secret scanning in pre-commit and CI.
- CI (GitHub Actions, brief §37): lint (ruff), type-check (mypy), unit tests (pytest), manifest validation, licence metadata validation, split and leakage validation, dependency-licence audit. **CI downloads no real dataset.** Fixtures are synthetic and generated by a seeded script, with planted exact duplicates, near-duplicates, grouped crops and mislabels; real dataset images never enter the repository (licence and size).
- Tests (brief §35): hash, manifest parsing, taxonomy mapping, duplicate grouping, split integrity, provenance, metrics, and the leakage invariants I1–I10; property-based tests for split invariants.

## 11. Risks and threats to validity

| id | risk | mitigation |
|---|---|---|
| R1 | licence laundering or mirror provenance | gates G1–G9; cross-source duplicate audit as provenance test |
| R2 | independence overstated: two of three sources are factory-AOI etch-stage crops | per-source reporting; interpret LOSO by modality |
| R3 | crop/scale policy changes defect pixel size and results | policy frozen in M2; sensitivity check |
| R4 | tiny held-out set (`pcb-defect`: 230 images) gives wide CIs | cluster bootstrap; always report n |
| R5 | EVREN API may limit how low the confidence threshold can go, truncating the PR curve | the confidence and IoU thresholds are documented parameters; check the lowest allowed value; otherwise headline mAP comes from `LocalProvider` on exported weights and the API gives operating-point metrics and a parity check |
| R6 | EVREN may withdraw a model family | resolved for now: YOLO11 and RT-DETR are offered (EVREN guide, per the maintainer); recheck before M7 |
| R7 | **EVREN may re-split or re-encode on import**, voiding leakage guarantees | UNKNOWN whether ZIP split folders are preserved: verify with a small import (M6) by comparing per-split item names with the local split file; Auto Split stays off; the local manifest is canonical; keep the uploaded ZIP and its SHA-256 |
| R8 | selection bias: AOI-guided crops, AOI-prescreened annotation, engineered defects | documented per source; conclusions limited to patch-level PCB surface-defect detection |
| R9 | single domain | no general "industrial vision" claim in v0.1; state the scope in the title and abstract |
| R10 | upstream drift (PCB-IND README vs record v4) | pin versions and checksums; archive evidence |
| R11 | disk, OneDrive, long Windows paths | D6; short paths; data outside the repo |
| R12 | Ultralytics is AGPL-3.0 | optional extra only, never vendored or bundled ([DEPENDENCIES](DEPENDENCIES.md)) |
| R13 | credits or time run short | minimal variant (≈ 18 runs); RT-DETR last |
| R14 | one reviewer, limited hours | review budget (D9); prioritised queue; report audit recall from the unflagged sample |

## 12. Decisions

Logged with evidence, reason, risk and revisit condition in [DECISIONS](DECISIONS.md).

| id | decision | status |
|---|---|---|
| D1 | domain: PCB surface defects | decided |
| D2 | sources: `dspcbsd-plus`, `pcb-ind`, `pcb-defect` accepted; `deeppcb` rejected | decided |
| D3 | code licence | **open**: a legal choice for the maintainer (recommendation: Apache-2.0) |
| D4 | dataset release licence: CC BY 4.0, provisional; no public release before the release checklist | decided |
| D5 | schema deviations from brief §11 | decided (accepted) |
| D6 | locations: repository stays; data and virtual environment outside OneDrive | decided |
| D7 | scale and crop policy: native resolution, about 300×300 ROI crops for `pcb-defect` | decided in principle, frozen in M2 |
| D8 | EVREN facts | recorded in [EVREN](EVREN.md); two items UNKNOWN |
| D9 | human review budget: about 300 label items and 300 calibration pairs | default, confirmed at M3 |
| D10 | analysis defaults: δ = 0.02 mAP50, 1,000 resamples, 3 seeds | default, revisited after the pilot |

## 13. Roadmap (proposed after M0; effort S/M/L)

| milestone | content | effort |
|---|---|---|
| M0 | this specification, gates, intake format, definition of done | S |
| M1 | source registry and provenance manifest generator: `openinspect source add/list/validate` | M |
| M2 | ingest: reproducible downloader, SHA-256 manifests, integrity, metadata, normalisation, image and annotation records | L |
| M3 | exact and near-duplicate audit, embeddings, calibration, review files | L |
| M4 | taxonomy mapping and label-quality audit with review queue | M |
| M5 | splits A0/A1/B, leakage tests in CI | M |
| M6 | YOLO/COCO export; maintainer uploads `v0.1-raw` and `v0.1-clean` in the EVREN UI and freezes them | S |
| M7 | local smoke test, then EVREN runs E1–E3 | L |
| M8 | `InferenceProvider`, `EvrenProvider`, `LocalProvider`, evaluator, benchmark runner | M |
| M9 | RT-DETR replicate, generalization-gap report | M |
| M10 | README, DATA_CARD, METHODOLOGY, BENCHMARK, SECURITY, CONTRIBUTING; public repository | M |
| M11 | research poster and SAYZEK project brief | M |
| optional | FastAPI backend (brief §33), after M9 | M |

## 14. Related work and positioning

To our knowledge, from a limited search on 2026-09-30 (a full literature review belongs to M10):

- DsPCBSD+ publishes a random 8:2 image-level split; the number of crops per board is not stated.
- PCB-IND removes near-duplicates by pHash (Hamming ≤ 3) but only within a production batch, and states the leakage concern itself.
- TrustPCB (DanielWei2002) builds a prediction-reliability framework on DsPCBSD+ (calibration, consistency, human-review referral); it targets model outputs, not dataset and benchmark validity.
- StructDamage (arXiv 2603.10484) and UniPCB (arXiv 2601.19222) aggregate many sources; their abstracts do not mention duplicate, leakage or source-held-out audits.

OpenInspect-Trust differs by making provenance, duplicate audit and source-held-out evaluation the object of study.

## Sign-off

Accepted 2026-09-30 by project-maintainer through the autonomous-execution directive; decisions are logged in [DECISIONS](DECISIONS.md). Open: D3 (code licence).
