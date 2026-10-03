# D1: final diagnosis

## What was added

Two matched seeds were added (jobs launched in the EVREN UI on 2026-10-03; configuration hash identical to all M7 jobs; checkpoints verified; evaluated with the unchanged M7 evaluator, and overall scores re-checked with plain Ultralytics `val`, which matched to 4 decimals):

| seed | C0 model | C1 model |
|---|---|---|
| 0 | C0-d1-s0 (M7) | C1-d1-s0 (M7) |
| 1 | C0-d1-s1, first-created replicate r1 (pre-registered choice) | **C1-d1-s1 (new)** |
| 2 | **C0-d1-s2 (new)** | **C1-d1-s2 (new)** |

## Result (C0 − C1, mAP50-95 points, same 408-image test set)

| seed | overall | probe | control | probe − control |
|---|---|---|---|---|
| 0 | +3.70 | +3.94 | **+3.09** | +0.84 |
| 1 | +2.91 | +5.82 | **−0.75** | +6.57 |
| 2 | +0.20 | +2.34 | **−1.68** | +4.02 |
| mean (SD) | +2.27 (1.84) | +4.03 (1.74) | **+0.22 (2.53)** | +3.81 (2.87) |
| sensitivity: seed 1 with the other C0 replicate (r2) | +4.04 | +6.07 | +1.47 | +4.60 |

Seed-aware intervals (two-stage bootstrap over A1 groups and seeds, 2000 draws): probe +0.92 to +7.51 (P(≤0) = 0.006); probe − control −0.65 to +8.17 (P(≤0) = 0.044); control −2.56 to +3.54.
Placebo (10,000 source-stratified cluster permutations, mean of 3 seeds): observed probe − control +3.81 vs null mean −0.02, SD 1.69 → **one-sided p = 0.009**.

## Outcome: **A, controls return to about zero**

The +3.09 control gain of seed 0 did not reproduce (−0.75, −1.68). Across the three seeds the D1 controls average +0.22, which is indistinguishable from D0's −0.17. The probe gain reproduced in every seed (+2.3 to +5.8). Training stochasticity of one run is a **plausible but unproven** explanation of the original D1 anomaly. It is consistent with the M7 evidence that identically configured EVREN runs differ by about 1–2 points on subsets: the two C0-d1-s1 replicates differ by 1.13 overall and 2.22 on controls.

Caveats, stated plainly:
- Seed 0 itself is still an outlier in its controls. It now counts as one of three draws, not as a contradiction.
- The seed-1 contrast depends on which C0 replicate is used (probe − control +6.57 vs +4.60). Both are positive. The pre-registered replicate was used for every summary statistic.
- With three seeds, the seed-only t-interval for D1 probe − control (−3.3 to +10.9) still includes zero. The combined interval only barely excludes zero (P ≈ 0.04). D1 now *supports* D0; it does not independently prove it.

## Dose-response inside D1

| probe exposure Δ (DINOv2-small) | n | seed 0 / 1 / 2 | mean |
|---|---|---|---|
| controls | 215 | +3.09 / −0.75 / −1.68 | +0.22 |
| Δ < 0.02 | 82 | +0.73 / −0.73 / −2.61 | −0.87 |
| 0.02–0.08 | 61 | +3.36 / +7.76 / +2.46 | +4.53 |
| Δ > 0.08 | 50 | +7.43 / +10.01 / +5.71 | **+7.72** |

In all three D1 seeds the most strongly exposed probes gain the most. The weakly exposed probes behave like controls.
