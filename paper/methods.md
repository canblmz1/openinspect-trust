<!-- Generated from manuscript.md (single source of truth); do not edit separately. -->

## 3. Datasets and Provenance

We pool three public PCB defect datasets, all licensed CC BY 4.0, into one release (v0.1; 4,420 images; 5,297 boxes). The release uses a shared four-class taxonomy: short, open, mouse bite, spurious copper.

| source | ingested | released images | released boxes | image form | acquisition (as described by the source) |
|---|---|---|---|---|---|
| DsPCBSD+ [11] | 10,259 | 1,768 | 2,472 | 226 px JPG (39 at 108 px) | production PCB images from an industrial manufacturer |
| PCB-IND [12] | 4,789 | 1,713 | 1,854 | 300 px JPG | inline industrial AOI system |
| PCB-Defect [13] | 230 | 939 crops | 971 | PNG crops, mostly 300 px | high-resolution images of laboratory-fabricated single-layer FR4 boards |

**Selection.** Released images contain only the four benchmark classes. DsPCBSD+ was sampled per class set to keep every source at or below 40% of the release. PCB-Defect's high-resolution images were cropped around defects (minimum side 300 px, 10% margin), and crops that cut a box or overlapped another crop were excluded.

**Provenance.** Every released image keeps its source item, SHA-256 hash and crop parent. Licence evidence, taxonomy mappings, label audits and split manifests are versioned and re-derived in continuous integration. Releasing a modified subset requires indicating the changes, as CC BY requires.


## 4. Group Construction

**Embeddings and thresholds.** Whole images are embedded with DINOv2-small [14] (primary) and DINOv2-base (sensitivity). Cosine thresholds were fixed by a rule committed before any model was trained:

- near level: 0.934, the 95%-recall point on synthetic transformed duplicates;
- family level: 0.918, the F1-optimal point on metadata-defined pools.

A perceptual-hash distance ≤ 4 flags review candidates. Each source uses its own primary level (family for DsPCBSD+ and PCB-IND, near for PCB-Defect).

**Constraint groups.** An image's constraint group is the transitive union of three links:

- its similarity component;
- its source metadata group (for PCB-IND, the board identifier in the file name);
- its crop parent (for PCB-Defect).

We call these *machine-detected visual-similarity groups*, not duplicates.

**Representation sensitivity.** The groups depend on the embedding. Within DsPCBSD+ and PCB-IND, DINOv2-small and DINOv2-base components barely overlap (adjusted Rand index about 0.01). About 43% of design-0 probes would not be exposed under DINOv2-base constraint groups.


## 5. Controlled Experimental Design

Each design D ∈ {D0, D1, D2} is an independent random draw with identical parameters:

| | D0 | D1 | D2 |
|---|---|---|---|
| test images (probes / controls) | 407 (194 / 213) | 408 (193 / 215) | 409 (194 / 215) |
| validation images | 698 | 699 | 698 |
| training images per condition | 3,102 | 3,099 | 3,103 |
| swapped images (mates ↔ replacements) | 213 | 214 | 210 |

**Roles.**

- **Probes** are test images whose other constraint-group members (*mates*) are eligible for training.
- **Controls** are whole constraint groups that neither condition trains on. Most of them (141 of 213 in D0) are singletons.
- **C0** trains on a common core plus the mates.
- **C1** trains on the same core plus an equal number of *replacements*: same source and, where possible, the same boxes per class, drawn from groups that touch no test or validation image.

**Integrity checks.** Within each design, C0 and C1 share byte-identical test and validation files and an identical core. The training sets differ exactly by mates versus replacements. No control's constraint group occurs in either training set, and every probe's group occurs in C0's training set and in none of C1's. The swap is not perfectly balanced: C0 contains 4–6% more training boxes than C1, mostly of the short and open classes.


## 6. Training and Evaluation Protocol

**Training.** All models are YOLO11n [15]. They were trained on the EVREN platform (SSYZ), starting from pretrained weights. All 31 jobs used one requested configuration:

- 100 epochs, batch 32, input size 640, SGD (lr0 0.01, lrf 0.01, momentum 0.937, weight decay 0.0005), warm-up 3 epochs, patience 20;
- the platform's validation cadence;
- standard Ultralytics augmentation (mosaic, HSV, translation, scale, horizontal flip).

The runs used a cosine learning-rate schedule (`cos_lr = True`) and label smoothing 0.1. These differ from the original analysis plan (linear schedule, no smoothing), but they are identical in every run, so every C0/C1 comparison remains configuration-matched. The effective configuration was read from each checkpoint and is identical across all checkpoints used.

**Seeds.** The eight matched C0/C1 pairs are D0 seeds 0–2, D1 seeds 0–2 and D2 seeds 0–1. Identically configured runs on the platform are not bit-reproducible: two replicates of one configuration differed by 1.13 points overall and 2.22 points on control images. For D1 seed 1, two C0 replicates exist. We pre-specified the first-created replicate and report the other as a sensitivity analysis.

**Evaluation.** All models were evaluated locally with one evaluator: Ultralytics 8.3.0 `DetectionValidator` with input size 640, confidence threshold 0.001, NMS IoU 0.7 and at most 300 detections. Metrics are COCO-style 101-point AP averaged over IoU 0.50:0.95 (mAP50-95, in percentage points). Per-image detections and matches were stored, so mAP can be recomputed on any subset of images. An independent re-evaluation with the plain `YOLO.val` interface reproduced every model's score to four decimals. Platform dashboard metrics were not used.

### 6.1 Estimands and statistics

**Estimands.**

- *Primary (pre-specified in the analysis plan committed before any training):* D0 probe mAP50-95(C0) − mAP50-95(C1), mean over three seeds.
- *Secondary:* the whole-test-set (overall) and control contrasts, and the probe-minus-control difference. Each subset contrast is computed on that subset; mAP is not additive over images.

**Uncertainty is reported separately by source:**

- **(A) Test-sampling uncertainty.** Cluster bootstrap over constraint groups of the test set, holding the trained models fixed (2,000 resamples).
- **(B) Training-seed uncertainty.** Student-t interval over the seed-level contrasts of a design. With two or three seeds these intervals are very wide.
- **(C) Combined uncertainty.** Two-stage bootstrap: test groups are resampled, then seeds are resampled with replacement, and the seed-mean contrast is recomputed (2,000 draws). This reflects both sources, but with only 2–3 seeds the seed component is itself poorly estimated.

**Pooling across designs.** We combine the designs by inverse-variance weighting of their combined-uncertainty estimates, with variances approximated from the bootstrap interval widths. This fixed-effect pooling assumes that the three designs estimate a common effect; the mixed replication (Section 8) suggests some heterogeneity, so the pooled interval may be too narrow.

**Placebo test.** We relabel whole test groups at random into pseudo-probes and pseudo-controls, matching the real per-source probe counts (10,000 relabellings). The probe-minus-control contrast is recomputed on the fixed predictions. These permutation p-values condition on the trained models; they show that the real probe set is atypical, not that exposure caused the difference.

**Exposure strength.** For every test image, Δ = (maximum cosine similarity to any C0 training image) − (maximum to any C1 training image), computed with both DINOv2 models. Probes are stratified as Δ < 0.02, 0.02 ≤ Δ ≤ 0.08 and Δ > 0.08. These strata were defined during an independent review after the first five seed pairs had been evaluated, and before the last three were trained. For the first five pairs the stratification is therefore post hoc; the last three pairs are an out-of-sample check. We also report the Spearman correlation between Δ and per-image recall gain on probes, with a cluster-bootstrap interval.

### 6.2 AI-assisted visual adjudication

To characterise what the machine-detected relationships look like, a multimodal AI model labelled image pairs on a seven-level scale: near-exact duplicate; same specimen or capture series; same design or layout family; structurally related; generically similar; unrelated; ambiguous.

**Review set.** We labelled 60 D0 probe images paired with their nearest exposing mate, and, for comparison, 30 controls paired with their nearest C0 training image.

**Protocol.** Two blinded passes were made by separate, fresh instances of the same underlying model. Each pass saw only anonymised, independently shuffled contact sheets. Disagreements (54 of 90) were then adjudicated with both labels visible.

**Agreement.** Agreement was weak on the fine scale (Cohen's κ 0.17, bootstrap 95% CI 0.03–0.30) and moderate on coarse groupings: same-instance κ 0.49, same-family-or-closer κ 0.45, ambiguous κ 0.74. Because both passes used the same model family, agreement measures internal consistency, not inter-rater reliability. We therefore use coarse categories only.

**Earlier review.** A separate earlier AI review covered the 300 machine-generated candidate pairs of the similarity audit.

**Independent human review of these pairs was not performed. It remains future validation, and every statement about the *nature* of the relationships in this paper is provisional on it.**

