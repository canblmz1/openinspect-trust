# OpenInspect-Trust

A reproducible dataset and benchmark assurance preflight for industrial vision.

**Status: early development.** Milestones 1 (source registry), 2 (ingest) and 3 (similarity and leakage audit) are implemented and have been run on three public PCB defect datasets. No model has been trained yet.

## What it is

OpenInspect-Trust is a reproducible pre-training dataset and benchmark assurance tool: before expensive model training it checks provenance, licence evidence, group dependence, visual similarity leakage and source dependence, and it reports each check with the evidence behind it. The PCB datasets are the research demonstrator, not the product. The core is platform-agnostic; [EVREN](docs/EVREN.md), the training platform used for the later experiments, is one integration target.

## Research question

> Can a provenance-aware, group-aware and source-aware assurance process detect when an industrial-vision benchmark gives an overly optimistic estimate of deployment performance?

The experiments that answer it compare three splits of the same pool (see [below](#how-the-benchmark-will-be-read)). The hypotheses H1–H4 and their decision rules are in [docs/SPEC.md](docs/SPEC.md) §2.

## What is not new

Finding exact and near-duplicate images is established tooling: [FiftyOne Brain](https://docs.voxel51.com/brain.html) (similarity and near-duplicate search), [Cleanlab](https://github.com/cleanlab/cleanlab) (data-issue detection, including near-duplicates) and [imagededup](https://github.com/idealo/imagededup) (hash- and CNN-based duplicate finding). OpenInspect-Trust does not claim to invent near-duplicate detection; it uses standard parts (perceptual hashes, DINOv2 embeddings, exact cosine search, connected components).

What it tests is whether the combination matters: provenance and licence evidence, a visual leakage audit, the integrity of the sources' own metadata groups across splits, source-aware evaluation on independent sources, and a reproducible evidence chain from archive hash to report.

## Why random splits can mislead

Defect-detection benchmarks are usually scored on a random train/test split of one pooled dataset. Images of the same board, the same production batch or the same source can land on both sides, so the score measures how well a model remembers its sources as much as how well it generalizes. Evidence from the sources themselves:

- DsPCBSD+ publishes a random image-level 8:2 train/validation split; its images are crops of larger boards and the paper does not say how many crops come from one board.
- The PCB-IND authors note that AOI systems capture overlapping images of the same defect region and that similar samples in train and test inflate results; they deduplicated only within a production batch.

## Method

1. Register sources with a verified licence, a pinned version and archived, hashed evidence (implemented).
2. Ingest with SHA-256 manifests and per-image provenance (implemented).
3. Audit the pool before training (implemented): exact and perceptual hashes, DINOv2 similarity with thresholds from a rule frozen before any result, visual similarity components, split leakage against random splits, the sources' own keys across splits, a dimensional assurance report and a human review queue.
4. Map source labels to a common taxonomy and audit label quality with human review (models never change labels).
5. Build three splits and train YOLO11n (later RT-DETR) on EVREN or locally; evaluate every model with one local evaluator.

Details, data contracts, invariants and risks: [docs/SPEC.md](docs/SPEC.md). Decisions and their evidence: [docs/DECISIONS.md](docs/DECISIONS.md).

## How the benchmark will be read

| split | what it is |
|---|---|
| A0 | raw, random split of the pool |
| A1 | cleaned, group-aware split of the same sources: no similarity component or metadata group crosses it |
| B | source-held-out: train on some sources, test on another |

A0 − A1 approximates the effect of split leakage. A1 − B approximates a residual source or domain shift. **A0 − B is not leakage:** between sources the acquisition hardware, the factory, the lighting, the resolution, the annotation style, the taxonomy and the label distribution all change, and each of them moves the score.

## Dataset sources

All three accepted sources are CC BY 4.0, read from the repository record and confirmed by the DOI registry; the records are archived and hashed in [manifests/evidence/](manifests/evidence/). Milestone 2 downloaded the archives on 2026-09-30 (size and checksum match the records) and ingested them; the raw data stays outside the repository.

| slug | dataset | images / boxes | original split | board or batch key in the archive | acquisition |
|---|---|---|---|---|---|
| `dspcbsd-plus` | [DsPCBSD+](https://doi.org/10.6084/m9.figshare.24970329.v1) | 10,259 / 20,276 | train / val, random 8:2 | none | factory AOI crops |
| `pcb-ind` | [PCB-IND v4](https://doi.org/10.5281/zenodo.19723114) | 4,789 / 5,932 | train / val / test | production batch and board side, from the file names | factory AOI ROI patches |
| `pcb-defect` | [PCB-Defect](https://doi.org/10.17632/vdj74sngvn.1) | 230 / 1,704 | none | board-design family, derived from the original scan names | lab boards, flatbed scan |

DeepPCB is rejected (its README and its LICENSE file disagree). Every decision and the licences of other candidates are in [LICENSE_MATRIX.md](LICENSE_MATRIX.md).

## What ingest found (Milestone 2)

The full per-source report is [reports/m2-ingest-report.md](reports/m2-ingest-report.md); the machine-readable reports are in [manifests/ingest/](manifests/ingest/).

- All three archives match the size and checksum published by their repositories, every member passes its zip CRC-32, all 15,278 images decode, and no SHA-256 occurs twice inside a source or across sources.
- PCB-IND is the only source with an explicit grouping key (production batch and board side, from the file name). Its official split never separates a (batch, side) group, yet 125 of its 685 batches occur in two splits.
- DsPCBSD+ has no board or scene identifier, so a board-level split there needs similarity clustering (Milestone 3).
- PCB-Defect's original scan names fall into 22 board-design families over 230 images, although the paper describes one image per board.
- Smaller issues: one PCB-IND box has zero height (it is missing from the COCO file), one PCB-IND VOC file is empty, 111 DsPCBSD+ images are 108×108 instead of 226×226, and 127 PCB-IND images carry no annotation (hard negatives).

## What the assurance audit found (Milestone 3)

The reports are in [reports/m3/](reports/m3/); every number in them is in [artifacts/m3/audit.json](artifacts/m3/audit.json).

## Results

The dataset-structure results of Milestone 3 are above. There are no model results yet; the roadmap is in [docs/SPEC.md](docs/SPEC.md) §13.

## Reproduction

Requirements: Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run openinspect source list
uv run openinspect source validate --strict
uv run pytest
```

The tests use small synthetic data and need neither the network nor the datasets; the integration tests check the committed reports against the committed manifests and against `artifacts/m3/audit.json`. To reproduce the ingest and the audit, set `OPENINSPECT_DATA_DIR` (below), then:

```bash
uv run openinspect ingest download --all
uv run openinspect ingest run --all
uv sync --extra embeddings            # torch (CPU build) and transformers, for the embedding stages only
uv run openinspect dedup features --all                               # about 26 min on a laptop CPU, cached
uv run openinspect dedup features --all --model dinov2-base           # the robustness check, about 60 min
uv run openinspect dedup synthetic --all
uv run openinspect dedup synthetic --all --model dinov2-base
uv run openinspect dedup run --all --robustness-model dinov2-base     # analysis, artifacts, reports, review pack
```

`dedup analyze` needs no model: it reads the caches. `dedup report` re-renders [reports/m3/](reports/m3/) from `artifacts/m3/audit.json` without any data. `dedup review` writes a local HTML contact sheet of the review queue into the data directory (it embeds dataset thumbnails, so it is never committed); decisions go into `artifacts/m3/review-candidates.csv`.

`validate` re-hashes every archived evidence file and checks it against [manifests/evidence/SHA256SUMS.txt](manifests/evidence/SHA256SUMS.txt). `validate --release public` additionally fails when an accepted source cannot be redistributed.

If this folder lives inside OneDrive, keep the virtual environment outside it, for example in PowerShell:

```powershell
$env:UV_PROJECT_ENVIRONMENT = "C:\venvs\openinspect-trust"
```

Raw data belongs outside the repository and outside OneDrive, under `OPENINSPECT_DATA_DIR` (see `.env.example`); `ingest` refuses a data directory inside either. About 0.9 GB is used by the three sources, plus about 110 MB of embedding caches and model weights.

## Licence

The code is licensed under [Apache-2.0](LICENSE) ([docs/DECISIONS.md](docs/DECISIONS.md), D3). The datasets keep their own licences (CC BY 4.0 for the three accepted sources) and are not part of this repository: see [LICENSE_MATRIX.md](LICENSE_MATRIX.md). The optional local-training extra will depend on Ultralytics, which is AGPL-3.0 ([docs/DEPENDENCIES.md](docs/DEPENDENCIES.md)).
