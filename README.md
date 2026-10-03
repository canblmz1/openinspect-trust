# OpenInspect-Trust

A reproducible dataset and benchmark assurance preflight for industrial vision.

**Status: research study frozen (3 October 2026).** Milestones 1–6, 5.5 and 7 are done. Milestone 7, the controlled YOLO11n experiments, was trained on EVREN and evaluated locally; no further training is planned. The grouped image pairs were characterised by AI visual adjudication only; **independent human validation was not performed**.

## Research finding

**Question.** When PCB test images have machine-detected group-related images (visual-similarity groups, crop parents, source board IDs) in the training set, is the performance difference concentrated on those exposed test images? How does that compare with evaluating on an unseen source?

**Controlled design.** Two training sets, C0 and C1, are evaluated on one byte-identical test set. C0 includes the group-mates of designated *probe* test images; C1 replaces them with profile-matched images. Unexposed *control* test images serve as a negative control. The study uses 3 independently drawn designs, 8 matched seed pairs of YOLO11n, one local evaluator (Ultralytics 8.3.0), and separate test-sampling and training-seed uncertainty.

**Frozen primary result.** In the first design, the probe difference mAP50-95(C0) − mAP50-95(C1) was +3.91 points (95% interval +0.41 to +7.65 including seed variation). Pooled over the three designs:

- probe effect +3.70 (+1.71 to +5.70);
- probe − control +3.37 (+0.68 to +6.06);
- whole-test-set effect about +2 points.

Replication was mixed: one design's anomalous control gain did not recur, and another design's second seed showed no probe-selective gain. Gains were concentrated among the most strongly exposed probes, while the continuous similarity–gain relationship was weak. AI visual review found no near-duplicates among 60 probe–mate pairs, so we call this *train–test group exposure*, not near-duplicate leakage.

**Source shift.** Holding out a whole source lowered mAP50-95 by 27–47 points (DsPCBSD+ 43.7 → 16.4, PCB-IND 56.8 → 19.2, PCB-Defect 47.6 → 0.3). Image size and format alone identify the source, so this measures acquisition/source shift, not an inability to learn the defect classes.

**Limitations.**

- no independent human validation;
- machine-detected groups;
- one architecture and one domain;
- 2–3 seeds per design;
- non-deterministic training;
- no deployment data.

Details: [paper draft](paper/manuscript.md) · [final verdict](reports/m7_final/FINAL_SCIENTIFIC_VERDICT.md) · [claim policy](reports/m7_final/FINAL_SAFE_CLAIMS.md). Preprint link: *to be added*.

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
5. Assemble a release with stable ids, provenance per item and three split regimes, A0, A1 and B, whose leakage invariants are measured and checked in CI (implemented).
6. Check training readiness before any training: re-derive the splits, build a controlled design whose conditions differ in one factor, measure how the splits depend on the representation, place the label findings in the release, probe how predictable the source is, and read every training package with two parsers that share no code with the exporter (implemented).
7. Train YOLO11n (later RT-DETR) on EVREN or locally with identical settings per regime; evaluate every model with one local evaluator.

Details, data contracts, invariants and risks: [docs/SPEC.md](docs/SPEC.md). Decisions and their evidence: [docs/DECISIONS.md](docs/DECISIONS.md).

## How the benchmark will be read

| split | what it is |
|---|---|
| A0 | raw, random split of the pool |
| A1 | cleaned, group-aware split of the same sources: no similarity component or metadata group crosses it |
| B (B-strict) | source-held-out: train on the other sources, test on the held-out one; training items that share a constraint with it are excluded |
| B-natural | source-held-out, keeping the machine-similar cross-source items in training |
| C0 / C1 | a controlled pair on one common test set: C0 trains on the group-mates of half of the test items (*probes*), C1 on replacements of the same source; the other test items (*controls*) have no group-mate in either |

C0 − C1 on the probes estimates the effect of training on group-mates of a test item, and the controls check that the swap alone changes nothing. A0 − A1 compares two different test sets (A1 has no PCB-Defect test item), so it is reported descriptively, not as a leakage effect (Milestone 5.5). A1 − B approximates a residual source or domain shift. **A0 − B is not leakage:** between sources the acquisition hardware, the factory, the lighting, the resolution, the annotation style, the taxonomy and the label distribution all change, and each of them moves the score.

## Dataset sources

All three accepted sources are CC BY 4.0, read from the repository record and confirmed by the DOI registry; the records are archived and hashed in [manifests/evidence/](manifests/evidence/). Milestone 2 downloaded the archives on 2026-09-30 (size and checksum match the records) and ingested them; the raw data stays outside the repository.

| slug | dataset | images / boxes | original split | board or batch key in the archive | acquisition |
|---|---|---|---|---|---|
| `dspcbsd-plus` | [DsPCBSD+](https://doi.org/10.6084/m9.figshare.24970329.v1) | 10,259 / 20,276 | train / val, random 8:2 | none | factory AOI crops |
| `pcb-ind` | [PCB-IND v4](https://doi.org/10.5281/zenodo.19723114) | 4,789 / 5,932 | train / val / test | production batch and board side, from the file names | factory AOI ROI patches |
| `pcb-defect` | [PCB-Defect](https://doi.org/10.17632/vdj74sngvn.1) | 230 / 1,704 | none | board-design family, derived from the original scan names | laboratory-fabricated boards (high-resolution images) |

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

## The release and its splits (Milestone 5)

The manifest is [manifests/releases/v0.1/release.json](manifests/releases/v0.1/release.json) (sources, versions, licences, taxonomy, crop policy, sample, every split with its method and measurements, invariants, M3 limitations, hashes, generating commit); the summary is [reports/m5/release.md](reports/m5/release.md). `items.parquet` carries per image the source, original file id, source version, licence, original and normalized labels, original and canonical split, `group_id`, `subgroup_id` and the visual similarity group; `excluded.parquet` lists every image that was left out and why.

- **4,420 images and 5,297 boxes** of the four benchmark classes: DsPCBSD+ 1,768 (40.0%, a class-stratified sample of 3,292 eligible images), PCB-IND 1,713 (38.8%, all eligible) and PCB-Defect 939 (21.2%): square crops of at least 300 native pixels around the defects of its scans (decision D7, frozen in T32). Global ids are `OI_<source>_<12 hex>` from the file's content, stable across rebuilds.
- **A0** (random, stratified by source and classes): 3,091 / 891 / 438. It cuts 248 metadata groups, 100 visual similarity components and 167 crop parents, and 727 similar pairs at the primary level lie across its splits: the naive benchmark, measured.
- **A1** (group-aware): whole groups of metadata keys, M3 visual similarity components, identical files and crop parents; 3,256 / 795 / 369, **0 supplied groups crossing (measured)**, and 0 similar pairs at the primary level across splits. DsPCBSD+ and PCB-IND are split 68/21/11 and 69/20/10; PCB-Defect forms one connected group of 859 of its 939 crops (design families chained by similarity components) and therefore sits in train and val only, so A0 and A1 are compared per source.
- **B** (source held out, 15% group-aware validation): one fold per source; training items that share a visual similarity component with the held-out source are excluded (85 PCB-IND items when DsPCBSD+ is held out, 181 DsPCBSD+ items when PCB-IND is held out); 0 constraints cross.
- Invariants I1 to I9 pass at build time and are re-checked from the committed files by `openinspect release check` in CI.

M5 read A0 − A1 as the leakage and split-structure effect; Milestone 5.5 showed that the two regimes evaluate different test sets and replaced that reading with a controlled design (below). A0 − B is not leakage. The visual-similarity audit behind A1 is machine-generated and has not been independently human-validated.

**EVREN smoke package.** `openinspect release smoke` wrote `openinspect-trust-v0.1-evren-smoke-yolo.zip` (YOLO Detection, 20 known items of A1: 10 train, 5 val, 5 test, all four classes in every split; file names are global ids) to `<OPENINSPECT_DATA_DIR>/exports/v0.1/`. Its SHA-256 and the expected split of every item were committed before any upload: [manifests/releases/v0.1/evren-smoke/](manifests/releases/v0.1/evren-smoke/). Milestone 6 imported it into EVREN (below).

## The EVREN import smoke test (Milestone 6)

On 2026-10-01 the maintainer imported the 20-item package in the EVREN web UI as a private dataset (YOLO Detection, Auto Split off) and froze it as version `v0.1-smoke`; no training was started. The observations are recorded as text in [observed.yaml](manifests/releases/v0.1/evren-smoke/observed.yaml) (no screenshot is committed), and `openinspect release smoke-verify` compares them with the expectation committed before the upload and with the ZIP: **PASS, 13 of 13 comparisons match** ([reports/m6/evren-smoke-test.md](reports/m6/evren-smoke-test.md)).

- Observed in EVREN: the ZIP was identified as YOLO Detection and imported with 20 images, 37 annotations, 4 classes and 0 unlabelled images; the class names and box counts match (`short` 8, `open` 8, `mouse_bite` 11, `spurious_copper` 10); the supplied split (10 / 5 / 5) was kept on import and in the frozen version; one item opened per split had the expected split and labels, with its boxes drawn where the defects are.
- Not tested: the split of each of the other 17 items, Auto Split, a full release or a COCO import, training and inference. Unknown: whether EVREN keeps the files byte for byte, and its APIs.
- EVREN's Dataset Health panel showed A / 81; that is the platform's score of a 20-image dataset, not an assurance result of this project.

Split preservation is therefore *observed for this package*; every later import is checked again against its split file (decision T38).

## Training readiness (Milestone 5.5)

Before any training, Milestone 5.5 asks: if two EVREN YOLO runs produce different scores, can we say which experimental factor caused the difference? **Verdict: TRAINING READY WITH EXPLICIT LIMITATIONS** ([reports/m5_5/TRAINING_READINESS.md](reports/m5_5/TRAINING_READINESS.md)). Every number is in [artifacts/m5_5/readiness.json](artifacts/m5_5/readiness.json), and `openinspect readiness check` re-derives the outputs from committed files in CI.

- **A0 − A1 is not a leakage effect.** A0 tests 438 items and A1 369; they share 38, A0 trains on 254 of A1's test items, and A1 has no PCB-Defect test item. The difference stays descriptive.
- **The controlled estimand is C0 − C1** on one common test set, in three seeded designs ([controlled-design.md](reports/m5_5/controlled-design.md)). Design 0: 407 test items (194 probes, 213 controls), 698 validation items, and 3,102 training items in both conditions with equal counts per source. Between the conditions only the probes' group-mates are swapped for replacements of the same source and, where possible, the same boxes per class (208 of 213); C0 exposes all 194 probes through 103 constraint groups, C1 exposes none.
- **B-strict and B-natural.** The M5 split B is now called B-strict; B-natural keeps the machine-similar cross-source items (85 PCB-IND items in the DsPCBSD+ fold, 181 DsPCBSD+ items in the PCB-IND fold). B-strict excludes only direct links, so 535 training items of its DsPCBSD+ fold stay transitively linked to the test set.
- **The splits depend materially on the representation** ([representation-sensitivity.md](reports/m5_5/representation-sensitivity.md)). An A1 built from DINOv2-base components moves 1,212 items (27.4%) to another split, and under base B-strict would exclude nothing; in design 0, 35 DINOv2-base similar pairs lie between C1's train and test sets (dspcbsd-plus 1, pcb-defect 33, pcb-ind 1; 46 in C0), so C0 − C1 is reported per source. A1, B and C are results *under the DINOv2-small grouping*.
- **PCB-Defect's giant group** (859 of its 939 crops) is a mixture (verdict E): transitive chaining of the scan-level components (chaining gap 0.22 over a diameter of 9 edges) and crop generation (components computed on the crops give a largest group of 71, a design family, instead of 859). It is diagnosed, not cut by hand ([pcb-defect-component.md](reports/m5_5/pcb-defect-component.md)).
- **Label findings in the release:** of the 437 M4 findings, 0 are FATAL, 1 is training-relevant (a box under 2 px), 48 are limitation-only and 388 concern images outside the release; nothing was relabelled ([release-label-quality.md](reports/m5_5/release-label-quality.md)).
- **Source identity is trivially predictable:** balanced accuracy 100% from image size and file format alone, 89.9% from box and colour statistics (majority baseline 40%); B measures a large source and domain shift ([source-probe.md](reports/m5_5/source-probe.md)).
- **Export:** All 14 YOLO packages of the M7 plan pass two independent readers: Ultralytics 8.4.171 in a separate environment and a parser that shares no code with the exporter; their boxes per class equal the release's ([export-validation.md](reports/m5_5/export-validation.md)).
- Human validation stays NOT PERFORMED (0 / 300 pairs reviewed), so the reports speak of machine-detected potential leakage, visual similarity groups and embedding-defined components only.

The M7 training plan (YOLO11n with one configuration for every run, three training seeds for C0 and C1) is [reports/m5_5/m7-plan.md](reports/m5_5/m7-plan.md). It was executed in Milestone 7 (plus replication seeds); see the Research finding section above and [reports/m7_final/](reports/m7_final/).

## Results

The dataset-structure results of Milestones 3 to 5.5 are above. There are no model results yet; the roadmap is in [docs/SPEC.md](docs/SPEC.md) §13.

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
uv run openinspect release build                                     # release v0.1: images, splits, manifest, reports/m5
uv run openinspect release check                                     # no data needed: hashes and invariants
uv run openinspect release smoke                                     # the EVREN smoke-test ZIP and its expected splits
uv run openinspect release smoke-verify                              # M6: the recorded EVREN observations against the expectation
uv run openinspect release smoke-report                              # no data needed: re-renders reports/m6 from its record
uv run openinspect readiness compute --ultralytics-python PYTHON     # M5.5, about 40 min; PYTHON: see below
uv run openinspect readiness check                                   # no data needed: re-derives the M5.5 outputs
```

`--ultralytics-python` names the interpreter of a separate environment with Ultralytics installed (`pip install ultralytics`): Ultralytics is AGPL-3.0, so it reads the packages from outside and is not a dependency of this project ([docs/DEPENDENCIES.md](docs/DEPENDENCIES.md)).

`dedup analyze` needs no model: it reads the caches. `dedup report` re-renders [reports/m3/](reports/m3/) from `artifacts/m3/audit.json` without any data. `dedup review` writes a local HTML contact sheet of the review queue into the data directory (it embeds dataset thumbnails, so it is never committed); decisions go into `artifacts/m3/review-candidates.csv`.

`validate` re-hashes every archived evidence file and checks it against [manifests/evidence/SHA256SUMS.txt](manifests/evidence/SHA256SUMS.txt). `validate --release public` additionally fails when an accepted source cannot be redistributed.

If this folder lives inside OneDrive, keep the virtual environment outside it, for example in PowerShell:

```powershell
$env:UV_PROJECT_ENVIRONMENT = "C:\venvs\openinspect-trust"
```

Raw data belongs outside the repository and outside OneDrive, under `OPENINSPECT_DATA_DIR` (see `.env.example`); `ingest` refuses a data directory inside either. About 0.9 GB is used by the three sources, plus about 0.6 GB of model weights and embedding caches.

## Licence

The code is licensed under [Apache-2.0](LICENSE) ([docs/DECISIONS.md](docs/DECISIONS.md), D3). The datasets keep their own licences (CC BY 4.0 for the three accepted sources) and are not part of this repository: see [LICENSE_MATRIX.md](LICENSE_MATRIX.md). The optional local-training extra will depend on Ultralytics, which is AGPL-3.0 ([docs/DEPENDENCIES.md](docs/DEPENDENCIES.md)).
