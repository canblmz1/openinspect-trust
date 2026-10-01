# OpenInspect-Trust

A reproducible dataset and benchmark assurance preflight for industrial vision.

**Status: early development.** Milestones 1 (source registry), 2 (ingest), 3 (similarity and leakage audit) and 4 (taxonomy and label audit) are implemented and have been run on three public PCB defect datasets. No model has been trained yet.

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
3. Audit the pool before training (implemented): exact and perceptual hashes, DINOv2 similarity with thresholds from a rule frozen before any result, visual similarity components, split leakage against random splits, the sources' own keys across splits, a dimensional assurance report and a review queue (not yet reviewed by a person).
4. Map source labels to a normalized taxonomy with a status and evidence per label, and flag suspicious annotations for review (implemented; original labels are never changed).
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

The reports are in [reports/m3/](reports/m3/) and every number in them is in [artifacts/m3/audit.json](artifacts/m3/audit.json); the short version is the [dataset assurance report](reports/m3/dataset-assurance.md). The rules were committed before any number was computed ([docs/M3_PROTOCOL.md](docs/M3_PROTOCOL.md)); corrections, the points of an independent red-team review and their effect are in [docs/M3_PROTOCOL_AMENDMENT.md](docs/M3_PROTOCOL_AMENDMENT.md). Similarity is the cosine of DINOv2-small embeddings of the whole image. A *visual similarity component* (a potential leakage group) links images through pairs at or above a threshold: it is an embedding-based similarity finding, machine-detected potential leakage, not proof that two images show the same object, and no image was removed.

**Human validation: NOT PERFORMED.** Reviewed pairs: 0 / 300 (`artifacts/m3/review-candidates.csv`, decision T29). The similarity findings have not yet been independently human-validated. Thresholds are based on proxy metadata, synthetic transforms and representation-based similarity.

- **Thresholds, from the frozen rule:** near-duplicate 0.934, same family or scene 0.918 (the review level coincides with it), pHash candidate 4 bits. Neither labelled pool reached precision 0.90 against its own proxy key (PCB-IND batch and side, PCB-Defect design family), so the rule's F1 fallback fixed the family level; at the near threshold every source keeps its target 95% of synthetic near-duplicates (achieved: DsPCBSD+ 95.7%, PCB-Defect 99.5%, PCB-IND 95.0%). The thresholds therefore rest on proxy labels.
- **DsPCBSD+ (official random 80/20 split):** at the family level, 216 components cross the train/validation boundary; they hold 1,983 of the 10,259 images (19.3%), and 482 of the 2,051 validation images (23.5%) have a training image at cosine 0.918 or more. At the stricter near-duplicate level: 196 components, 1,191 images (11.6%), 325 validation images (15.8%). Random 80/20 splits of the same images give about as many crossing components (227.7 ± 10.7), so the official split behaves as if it ignored visual similarity.
- **PCB-IND (official train/val/test):** 57 components cross a split (33 train/val, 38 train/test, 18 val/test), holding 842 of 4,789 images (17.6%); 16.5% of the validation and 17.8% of the test images have a training image at 0.918 or more. That is about half of what random splits give (109.1 ± 6.6), because the split keeps each (batch, side) group together; but every one of the 832 cross-split similar pairs joins two *different* batches, which a batch-key check cannot see. With pHash at 3 bits there are 0 pairs inside a batch (the authors removed those) and 435 pairs across batches, 123 of them across a split. Separately, 125 of the 685 batches have images in two splits.
- **PCB-Defect (no official split):** the most similar other image shares the design family for 72.2% of the images (4.9% by chance). The components chain (one near-level component holds 111 of the 230 images, with a chaining gap of 0.22), so its groups are chains, not duplicate sets.
- **Across sources:** no identical file; 115 pairs between DsPCBSD+ and PCB-IND reach the family level and 30 the near-duplicate level; none involve PCB-Defect.
- **A group-aware split** with the official sizes has no crossing component (measured) and lowers the 95th percentile of each DsPCBSD+ validation image's highest cosine to training from 0.964 to 0.912.
- **Robustness:** DINOv2-base, calibrated by the same rule, keeps the direction of every finding (the DsPCBSD+ split crosses about as many components as random splits, the PCB-IND split fewer), but at its own, stricter threshold (0.958) it finds far fewer crossing components (DsPCBSD+ 83 instead of 216, PCB-IND 7 instead of 57) and misses more of the synthetic near-duplicates (its near threshold keeps 81.6% of the DsPCBSD+ and 84.1% of the PCB-IND copies, against a 95% target). The direction is robust to the representation; the size is not, and only a human review could say which scale is closer.
- **Assessment (dimensional, no score):** DsPCBSD+ and PCB-IND are *potentially optimistic* as split; PCB-Defect cannot be assessed (no split); independent source validation is missing, and source diversity is low (two acquisition kinds for three sources).

Whether this potential leakage changes model scores is measured by the experiments (Milestone 7), not here.

## What the taxonomy and label audit found (Milestone 4)

The taxonomy is [configs/taxonomy.yaml](configs/taxonomy.yaml), explained in [docs/TAXONOMY.md](docs/TAXONOMY.md); the reports are in [reports/m4/](reports/m4/). Every source label is mapped once to a normalized class with a status (EXACT, COMPATIBLE, AMBIGUOUS, SOURCE_SPECIFIC, REJECTED) and the evidence from the source's paper; equal names were never enough. Original labels are kept next to the normalized ones in `artifacts/m4/taxonomy-map.parquet`.

- **Comparable across all three sources: `short`, `open`, `mouse_bite`, `spurious_copper`.** Two of the twelve mappings behind them are COMPATIBLE (DsPCBSD+ spurious copper is broader; PCB-Defect's mouse-bite definition also mentions board edges).
- Shared by two sources only: `spur` and `scratch`. Ambiguous and not merged: PCB-IND `copper_burr` (it looks like a spur in the definition but sits at hole and pad edges) and `stain`. Source-specific: missing copper, missing pad, hole breakout and the two foreign-object classes.
- An image with a box of any other class is excluded whole, so a cross-source release keeps 3,292 DsPCBSD+ and 1,713 PCB-IND images (plus 127 PCB-IND hard negatives) and no whole PCB-Defect scan: every scan also holds a spur or missing pad, so its 1,132 benchmark boxes need crops (M5).
- The label audit flags 437 cases for review and changes nothing: 8 geometry problems (one zero-height box, tiny and extremely thin boxes), 4 boxes drawn twice with different labels, 332 boxes of atypical size for their class, 2 format disagreements, 89 near-identical image pairs (both representations agree) with different label sets, and the 2 ambiguous mappings. Nobody has reviewed the queue yet.

## Results

The dataset-structure results of Milestones 3 and 4 are above. There are no model results yet; the roadmap is in [docs/SPEC.md](docs/SPEC.md) §13.

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
uv run openinspect taxonomy check                                    # no data needed
uv run openinspect taxonomy audit --all                              # map, review queue, reports/m4
```

`dedup analyze` needs no model: it reads the caches. `dedup report` re-renders [reports/m3/](reports/m3/) from `artifacts/m3/audit.json` without any data. `dedup review` writes a local HTML contact sheet of the review queue into the data directory (it embeds dataset thumbnails, so it is never committed); decisions go into `artifacts/m3/review-candidates.csv`.

`validate` re-hashes every archived evidence file and checks it against [manifests/evidence/SHA256SUMS.txt](manifests/evidence/SHA256SUMS.txt). `validate --release public` additionally fails when an accepted source cannot be redistributed.

If this folder lives inside OneDrive, keep the virtual environment outside it, for example in PowerShell:

```powershell
$env:UV_PROJECT_ENVIRONMENT = "C:\venvs\openinspect-trust"
```

Raw data belongs outside the repository and outside OneDrive, under `OPENINSPECT_DATA_DIR` (see `.env.example`); `ingest` refuses a data directory inside either. About 0.9 GB is used by the three sources, plus about 0.6 GB of model weights and embedding caches.

## Licence

The code is licensed under [Apache-2.0](LICENSE) ([docs/DECISIONS.md](docs/DECISIONS.md), D3). The datasets keep their own licences (CC BY 4.0 for the three accepted sources) and are not part of this repository: see [LICENSE_MATRIX.md](LICENSE_MATRIX.md). The optional local-training extra will depend on Ultralytics, which is AGPL-3.0 ([docs/DEPENDENCIES.md](docs/DEPENDENCIES.md)).
