# OpenInspect-Trust

Provenance-aware cross-dataset benchmark tooling for industrial defect detection.

**Status: early development.** Milestones 1 (source registry) and 2 (ingest) are implemented and have been run on the three accepted sources. There are no experimental results yet.

## Problem

Defect-detection benchmarks are usually scored on a random train/test split of one pooled dataset. Images of the same board, the same production batch or the same source can land on both sides of the split, and exact or near-duplicate images can appear in both train and test. The score then measures how well a model remembers its sources as much as how well it generalizes.

## Research question

Do conventional random train/test splits overestimate industrial visual defect detection performance compared with provenance-aware, source-held-out evaluation?

Secondary questions: how much do exact duplicates, near-duplicates and source leakage distort scores, and can data-centric cleaning improve cross-source generalization more than a bigger model? The hypotheses H1–H4 and their decision rules are in [docs/SPEC.md](docs/SPEC.md) §2.

## Why random splits can mislead

Evidence from the candidate sources themselves:

- DsPCBSD+ publishes a random image-level 8:2 train/validation split; its images are crops of larger boards and the paper does not say how many crops come from one board.
- The PCB-IND authors note that AOI systems capture overlapping images of the same defect region and that similar samples in train and test inflate results; they deduplicated only within a production batch.

Whether this matters quantitatively is what the project measures.

## Method

1. Register sources with a verified licence, a pinned version and archived, hashed evidence (implemented).
2. Ingest with SHA-256 manifests and per-image provenance (implemented: no exact duplicate inside or across the three sources); audit near duplicates across sources.
3. Map source labels to a common taxonomy; audit label quality with human review (models never change labels).
4. Build three splits: random on the raw pool (A0), group-aware random on the cleaned pool (A1), and source-held-out / leave-one-source-out (B).
5. Train YOLO11n (and later RT-DETR) on [EVREN](docs/EVREN.md); evaluate every model with one local evaluator; report the generalization gap with confidence intervals.

Details, data contracts, invariants and risks: [docs/SPEC.md](docs/SPEC.md). Decisions and their evidence: [docs/DECISIONS.md](docs/DECISIONS.md).

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

## Results

None yet. The roadmap is in [docs/SPEC.md](docs/SPEC.md) §13.

## Reproduction

Requirements: Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run openinspect source list
uv run openinspect source show pcb-ind
uv run openinspect source validate --strict
uv run pytest
```

The tests use small synthetic archives and need neither the network nor the datasets. To reproduce the ingest, set `OPENINSPECT_DATA_DIR` (below), then:

```bash
uv run openinspect ingest download --all
uv run openinspect ingest run --all
```

`download` keeps a file only if its size and checksum equal the manifest's. `run` extracts the archives, reads them with one adapter per source, writes the image and annotation records under the data directory, and regenerates [manifests/ingest/](manifests/ingest/) and [reports/m2-ingest-report.md](reports/m2-ingest-report.md). `uv run pytest` checks the committed reports against the committed manifests without the data.

`validate` re-hashes every archived evidence file and checks it against [manifests/evidence/SHA256SUMS.txt](manifests/evidence/SHA256SUMS.txt). `validate --release public` additionally fails when an accepted source cannot be redistributed.

If this folder lives inside OneDrive, keep the virtual environment outside it, for example in PowerShell:

```powershell
$env:UV_PROJECT_ENVIRONMENT = "C:\venvs\openinspect-trust"
```

Raw data belongs outside the repository and outside OneDrive, under `OPENINSPECT_DATA_DIR` (see `.env.example`); `ingest` refuses a data directory inside either. About 0.9 GB is used by the three sources.

## Licence

The code is licensed under [Apache-2.0](LICENSE) ([docs/DECISIONS.md](docs/DECISIONS.md), D3). The datasets keep their own licences (CC BY 4.0 for the three accepted sources) and are not part of this repository: see [LICENSE_MATRIX.md](LICENSE_MATRIX.md). The optional local-training extra will depend on Ultralytics, which is AGPL-3.0 ([docs/DEPENDENCIES.md](docs/DEPENDENCIES.md)).
