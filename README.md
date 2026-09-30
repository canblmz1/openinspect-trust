# OpenInspect-Trust

Provenance-aware cross-dataset benchmark tooling for industrial defect detection.

**Status: early development.** Milestone 1 (the source registry) is implemented. There are no experimental results yet.

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
2. Ingest with SHA-256 manifests and per-image provenance; audit exact and near duplicates across sources.
3. Map source labels to a common taxonomy; audit label quality with human review (models never change labels).
4. Build three splits: random on the raw pool (A0), group-aware random on the cleaned pool (A1), and source-held-out / leave-one-source-out (B).
5. Train YOLO11n (and later RT-DETR) on [EVREN](docs/EVREN.md); evaluate every model with one local evaluator; report the generalization gap with confidence intervals.

Details, data contracts, invariants and risks: [docs/SPEC.md](docs/SPEC.md). Decisions and their evidence: [docs/DECISIONS.md](docs/DECISIONS.md).

## Dataset sources

All three accepted sources are CC BY 4.0, read from the repository record and confirmed by the DOI registry; the records are archived and hashed in [manifests/evidence/](manifests/evidence/). Nothing has been downloaded yet.

| slug | dataset | images / boxes | acquisition |
|---|---|---|---|
| `dspcbsd-plus` | [DsPCBSD+](https://doi.org/10.6084/m9.figshare.24970329.v1) | 10,259 / 20,276 | factory AOI crops |
| `pcb-ind` | [PCB-IND v4](https://doi.org/10.5281/zenodo.19723114) | 4,789 / 5,932 | factory AOI ROI patches |
| `pcb-defect` | [PCB-Defect](https://doi.org/10.17632/vdj74sngvn.1) | 230 / 1,704 | lab boards, flatbed scan |

DeepPCB is rejected (its README and its LICENSE file disagree). Every decision and the licences of other candidates are in [LICENSE_MATRIX.md](LICENSE_MATRIX.md).

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

`validate` re-hashes every archived evidence file and checks it against [manifests/evidence/SHA256SUMS.txt](manifests/evidence/SHA256SUMS.txt). `validate --release public` additionally fails when an accepted source cannot be redistributed.

If this folder lives inside OneDrive, keep the virtual environment outside it, for example in PowerShell:

```powershell
$env:UV_PROJECT_ENVIRONMENT = "C:\venvs\openinspect-trust"
```

Raw data belongs outside the repository and outside OneDrive, under `OPENINSPECT_DATA_DIR` (see `.env.example`).

## Licence

The code is licensed under [Apache-2.0](LICENSE) ([docs/DECISIONS.md](docs/DECISIONS.md), D3). The datasets keep their own licences (CC BY 4.0 for the three accepted sources) and are not part of this repository: see [LICENSE_MATRIX.md](LICENSE_MATRIX.md). The optional local-training extra will depend on Ultralytics, which is AGPL-3.0 ([docs/DEPENDENCIES.md](docs/DEPENDENCIES.md)).
