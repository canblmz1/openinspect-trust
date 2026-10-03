# Statistical red-team

> **Pre-replication record, superseded 2026-10-03.** The final numbers are in `reports/m7_final/` (5 replication runs added; the analysis was re-run with 2,000 bootstrap draws and 10,000 placebo relabellings, so intervals differ from those below). Do not cite numbers from this file; see `reports/m7_final/FINAL_SCIENTIFIC_VERDICT.md`.

## 0. Reproduction from raw artifacts: PASS (tolerance 0.01 pp; observed 0.0000 pp)

I re-evaluated all 20 checkpoints with a script that does not import or copy `m7_evaluate.py` (`scripts/reeval.py`). It extracts each package's test split and runs plain `YOLO(pt).val(split="test", imgsz=640, conf=0.001, iou=0.7, max_det=300, rect)` in the M7 environment: Ultralytics 8.3.0, torch 2.4.1 CPU. A second, independent COCO-101 AP implementation (`scripts/lib.py`) recomputed mAP from the saved per-image detections.

| run | package | test images | reported mAP50-95 | Ultralytics re-run | own AP on saved detections |
|---|---|---|---|---|---|
| C0-d0-s0 / s1 / s2 | C0-d0 | 407 | 52.35 / 53.14 / 53.08 | identical | identical |
| C1-d0-s0 / s1 / s2 | C1-d0 (own package) | 407 | 50.59 / 50.79 / 51.92 | identical | identical |
| C0-d1-s0 / C1-d1-s0 | C0-d1 / C1-d1 | 408 | 54.48 / 50.77 | identical | identical |
| C0-d2-s0 / C1-d2-s0 | C0-d2 / C1-d2 | 409 | 53.04 / 50.35 | identical | identical |
| noise C1-d0-s0 replicate | C1-d0 | 407 | (51.22) | 51.22 | 51.22 |
| noise C0-d1-s1 ×2 | C0-d1 | 408 | (54.52 / 53.39) | identical | identical |
| A0 / A1 | A0 / A1 | 438 / 369 | 55.43 / 52.73 | identical | identical |
| B-strict / B-natural DsPCBSD+ | | 1,768 | 16.37 / 15.21 | identical | identical |
| B-strict / B-natural PCB-IND | | 1,713 | 19.17 / 19.72 | identical | identical |
| B-strict PCB-Defect | | 939 | 0.33 | identical | identical |

The largest absolute difference across the 20 runs is below 0.0001 pp (`data/repro_table.csv`). C1 was evaluated on its *own* package, not on C0's, and the test-set digests match, so the C0/C1 test identity is confirmed independently as well. The point estimates in `reports/m7` are exactly reproducible.

## 1. Point estimates (D0, mean of 3 seeds; recomputed)

overall +1.76, probe +3.91, control −0.17, probe − control +4.08 pp. All match the M7 report.

## 2. Training noise measured on the *subsets*

Only the overall noise floor (1.13 pp) was reported before. Measured on the same subsets as the effect, it is larger. Same-condition pairs used: the 3 C0 seeds pairwise, the 3 C1 seeds pairwise, and the C1-s0 replicate against the 3 C1 seeds (9 pairs on the D0 test set).

| subset | RMS difference between two models of the *same* condition (pp) | observed C0 − C1 (3-seed mean) | ratio |
|---|---|---|---|
| overall | 0.77 | +1.76 | 2.3 |
| probe | 1.76 | +3.91 | 2.2 |
| control | 1.19 | −0.17 | — |
| probe − control | 2.71 | +4.08 | 1.5 |

For a *single* pair of runs, the probe − control contrast has a training-noise SD of about 2.7 pp, two-thirds of the effect. Seed 2's contrast (+0.28) is well inside that noise. Averaging three seeds reduces the noise SD to about 2.71/√3 ≈ 1.6 pp.

There are 12 cross-condition pairs (each C0 seed × each C1 model including the replicate). All have probe > 0 (min +1.55) and overall > 0 (min +0.43). The probe − control contrast is positive in all 12 (min +0.28, mean +4.36).

## 3. Interval estimates for D0 under several uncertainty models

| method | overall | probe | control | probe − control | P(probe−control ≤ 0) |
|---|---|---|---|---|---|
| i.i.d. image bootstrap (wrong unit, for reference) | 0.41 to 3.31 | 1.63 to 6.45 | −1.74 to 1.38 | 1.26 to 6.85 | 0.001 |
| cluster bootstrap, A1 constraint groups, same resample across seeds (= M7 method) | 0.27 to 3.83 | 1.43 to 6.70 | −1.68 to 1.67 | 1.05 to 7.12 | 0.004 |
| **hierarchical: resample groups AND seeds** | **−0.01 to 4.05** | **0.67 to 7.45** | −2.29 to 2.31 | **−0.68 to 8.46** | **0.049** |
| cluster bootstrap + per-seed training noise (SD from §2) | −0.04 to 4.04 | 0.86 to 7.52 | −2.09 to 2.11 | 0.15 to 7.89 | 0.022 |
| seed-only t-interval (df = 2) | 0.27 to 3.24 | −1.82 to 9.64 | −3.82 to 3.49 | −5.19 to 13.34 | — |

1000 bootstrap draws each, RNG seed 12345 (`data/stats.json`). The M7 method was re-implemented independently and its interval (probe − control +1.05 to +7.12) agrees with the reported +1.06 to +7.33 within Monte-Carlo error.

## 4. Answers to the audit questions

1. **Is the bootstrap unit correct?** The A1 constraint group is a defensible unit and better than images. Visually, though, groups are noisy (`GROUP_VALIDITY.md`), and cross-source chaining makes some groups large and arbitrary. Clustering changes intervals only modestly relative to i.i.d. here (DiD lower bound 1.26 → 1.05).
2. **Does group dependence require cluster bootstrap?** Yes in principle, and it was used. It is not where the weakness lies.
3. **Does the reported CI ignore training-seed uncertainty?** **Yes, and this is the material omission.** The M7 interval reuses one test resample for all three seeds, so it treats the three models as fixed. Adding seed resampling widens the overall interval to touch zero (−0.01) and the probe − control interval to include zero (−0.68 to +8.46).
4. **Is averaging three seeds defensible?** As a point estimate, yes. As a basis for inference, three seeds give a t-interval with 2 degrees of freedom. That interval includes zero for probe, control and the difference. Only the overall effect survives the seed-only interval (+0.27 to +3.24), because the overall differences are consistent across seeds (1.75, 2.36, 1.16).
5. **Would a hierarchical model change the conclusion?** It changes the strength, not the sign. Probe > 0 survives every method (P ≤ 0.01 except the seed-only t). Probe − control is borderline (P ≈ 0.02–0.05) once training noise is included.
6. **Does a permutation test change it?** The test-side placebo (`PLACEBO_TESTS.md`) supports D0 (p 0.009) and D2 (p 0.008) and rejects nothing in D1 (p 0.35). It conditions on the trained models.
7. **Incorporating the training-noise floor:** with subset-specific noise SDs (§2) the probe effect stays positive (0.86 to 7.52). The probe − control interval shrinks to just above zero (0.15 to 7.89). Comparing the 3-seed overall effect with the old 1.13 pp floor: 1.76 / 1.13 = 1.6×. That is "larger than noise" only in the weak sense.

## 5. Combined evidence across designs

Probe − control in D0 (mean of 3), D1 and D2: +4.08, +0.84, +4.58. The inverse-variance mean, with each design's variance = cluster-bootstrap variance (taken from its 95% CI width) + training noise (2.71²/k seeds), is +3.55 pp (SE 1.64). Its approximate 95% interval is +0.3 to +6.8. The weights are 55% D0, 25% D2 and 20% D1. Because D1 is not exchangeable with D0, this pooled value is indicative, not a headline.

## Bottom line

The point estimates are exactly reproducible. With training-seed uncertainty included, the overall C0 − C1 effect and the probe − control contrast are **borderline** on D0 alone, at about p 0.02–0.05. The probe-specific gain is robust (P ≤ 0.01). Statistical strength comes mainly from two things together: the replication of the probe pattern in D2, and the dose-response gradient across all designs. A single hero interval does not carry it.
