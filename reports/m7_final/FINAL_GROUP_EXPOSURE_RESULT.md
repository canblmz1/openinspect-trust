# Final result: train–test group exposure (frozen 2026-10-03)

**AI visual adjudication was performed; independent human validation was not performed.** The groups are machine-detected (DINOv2-small similarity components, crop parents, source metadata). AI review of 60 probe→mate pairs found 0 near-duplicates; it found mostly same-family or structurally related images, and 27% with no visible relation.

## Runs

8 matched C0/C1 seed pairs on fixed, byte-identical test sets: D0 seeds 0–2 (M7), D1 seeds 0–2 (seeds 1 and 2 completed on 2026-10-03), and D2 seeds 0–1 (seed 1 new). All 31 EVREN jobs share one requested configuration; every checkpoint used carries the same effective-configuration hash (`d021d7fa…`), and all were evaluated with Ultralytics 8.3.0 (imgsz 640, conf 0.001, iou 0.7, max_det 300). The point estimates for all 25 evaluated models reproduce with an independent plain-`val` re-run.

## Replication table (C0 − C1, mAP50-95 points)

| design | seed | overall | probe | control | probe − control |
|---|---|---|---|---|---|
| D0 | 0 | +1.75 | +3.65 | −0.56 | +4.22 |
| D0 | 1 | +2.36 | +6.34 | −1.40 | +7.73 |
| D0 | 2 | +1.16 | +1.74 | +1.46 | +0.28 |
| D1 | 0 | +3.70 | +3.94 | +3.09 | +0.84 |
| D1 | 1 | +2.91 | +5.82 | −0.75 | +6.57 |
| D1 | 2 | +0.20 | +2.34 | −1.68 | +4.02 |
| D2 | 0 | +2.69 | +4.60 | +0.02 | +4.58 |
| D2 | 1 | +1.65 | +1.69 | +1.68 | +0.01 |
| **all 8: mean** | | **+2.05** | **+3.77** | **+0.23** | **+3.53** |
| min / max | | +0.20 / +3.70 | +1.69 / +6.34 | −1.68 / +3.09 | +0.01 / +7.73 |

- Probe gain: positive in **8 of 8** seed pairs.
- Probe − control: positive in 8 of 8, but two are about 0 (D0 s2 +0.28, D2 s1 +0.01).
- Controls: mean +0.23 points, centred on zero.

## Seed-aware uncertainty (`FINAL_SEED_AWARE_STATS.csv`)

A = test sampling only (cluster bootstrap, seeds fixed). B = training seeds only (t-interval). C = combined two-stage bootstrap (groups, then seeds).

| estimand | point | A | B | C | P(≤0) under C |
|---|---|---|---|---|---|
| **D0 probe (primary, pre-registered)** | **+3.91** | +1.27 to +6.77 | −1.82 to +9.64 | **+0.41 to +7.65** | **0.014** |
| D0 probe − control | +4.08 | +0.79 to +7.29 | −5.19 to +13.34 | −0.97 to +9.07 | 0.066 |
| D0 overall (secondary) | +1.76 | +0.20 to +3.76 | +0.27 to +3.24 | −0.05 to +3.95 | 0.030 |
| D1 probe − control | +3.81 | +0.84 to +6.94 | −3.31 to +10.94 | −0.65 to +8.17 | 0.044 |
| D2 probe − control | +2.30 | −0.87 to +5.66 | (2 seeds) | −2.42 to +6.76 | 0.143 |
| pooled probe (D0, D1, D2, inverse-variance) | +3.70 | | | +1.71 to +5.70 | |
| pooled probe − control | +3.37 | | | +0.68 to +6.06 | |
| pooled overall | +2.03 | | | +0.79 to +3.27 | |

With only 2–3 seeds per design the seed-only intervals (B) are wide, and they all include zero except D0 overall. The combined interval is the defensible headline. The pooled estimate across the three independently drawn designs is the strongest single statement: **+3.7 points on exposed probes (95% +1.7 to +5.7) and +3.4 points beyond controls (+0.7 to +6.1)**.

## Placebo (`FINAL_PLACEBO_RESULTS.csv`; 10,000 source-stratified cluster relabellings each)

| design | seeds | observed probe − control | null mean (SD) | one-sided p | two-sided p |
|---|---|---|---|---|---|
| D0 | 3 | +4.08 | +0.03 (1.82) | **0.013** | 0.024 |
| D1 | 3 | +3.81 | −0.02 (1.69) | **0.009** | 0.019 |
| D2 | 2 | +2.30 | +0.03 (1.62) | 0.078 | 0.154 |

The earlier interim values were D0 ≈ 0.01, D1 ≈ 0.35 and D2 ≈ 0.01. Now D1 confirms, and D2 has weakened after its second seed. Permutation p-values condition on the trained models and are not causal proof.

## Exposure strength (dose-response; `FINAL_DOSE_RESPONSE.csv`, `fig1_exposure_gain.png`)

The bins (exposure Δ = max cosine to C0 train − max cosine to C1 train; < 0.02 / 0.02–0.08 / > 0.08) were fixed in the independent review after the first five seed pairs had been evaluated and **before** the 5 new runs existed. The three seed pairs those runs completed (D1 s1, D1 s2, D2 s1) are therefore an out-of-sample check of the binned pattern; for the first five pairs the binning is post hoc.

| bin (DINOv2-small) | images per design | mean over 8 seed pairs | min | seeds > 0 |
|---|---|---|---|---|
| controls | 213–215 | +0.23 | −1.68 | 4/8 |
| probes Δ < 0.02 | 69–82 | +0.00 | −3.11 | 4/8 |
| probes 0.02–0.08 | 60–61 | +2.41 | −2.62 | 6/8 |
| **probes Δ > 0.08** | 50–64 | **+6.85** | **+4.52** | **8/8** |

- Strongly exposed probes minus controls, per seed: +6.8, +9.3, +4.8, +4.3, +10.8, +7.4, +6.7, +2.8. All 8 are positive; mean +6.6.
- New out-of-sample seeds in the top bin: +10.01, +5.71 (D1) and +4.52 (D2). Each exceeds its controls.
- **DINOv2-base:** the same pattern. Top-bin means are +6.6 (D0), +10.4 (D1) and +7.4 (D2), and every seed is ≥ +5.9.
- **Continuous analysis is weak.** The Spearman correlation between exposure Δ and per-image recall gain on probes is +0.15 (D0, 95% +0.03 to +0.29), +0.12 (D1), +0.08 (D2) with small embeddings, and +0.11, +0.13, +0.10 with base. Only D0-small excludes zero; per-seed values are all positive (0.02–0.22).

**Reading:** the effect is not a smooth, strong monotone function of similarity. It is concentrated in the most strongly exposed third of the probes, while weakly exposed probes behave like unexposed controls. Allowed wording: "gains were concentrated among the most strongly exposed test images and were directionally larger at higher visual similarity". Not allowed: "higher similarity causes higher gain".

## Pre-planned split by link type (`probe_link_split.csv`)

| design | visually linked probes: mean (per seed) | metadata-only probes: mean (per seed) |
|---|---|---|
| D0 | +3.15 (+2.75, +5.02, +1.69) | +11.31 (+15.57, +12.20, +6.16) |
| D1 | +4.89 (+4.88, +6.75, +3.04) | +2.39 (+6.57, +0.73, −0.14) |
| D2 | +3.08 (+3.89, +2.26) | +0.41 (+3.55, −2.73) |

- **Visually linked probes:** positive in 8/8 seed pairs.
- **Metadata-only (board ID or design family) probes:** a large D0 gain that did not replicate.
- This supports "visual group exposure" and argues against "same-board exposure".

## Visual categories (frozen AI adjudication, D0 sample, coarse categories only)

| coarse category of probe → nearest mate | probes | boxes | D0 gain (3 seeds) |
|---|---|---|---|
| same-instance-like | 4 | 5 | +0.1 (+5.8 / −17.8 / +12.4): uninterpretable |
| same-family-like | 9 | 10 | +3.8 |
| structurally related | 28 | 32 | +2.0 |
| unrelated | 16 | 16 | −0.3 |
| ambiguous | 3 | 4 | +3.4 |

The ordering is directional (family > structural > unrelated), but the subsets are tiny. This table is not used as evidence on its own.

## Conclusion

Training on a test image's machine-detected group-mates raises mAP50-95 on that image by about 3.7 points (pooled over three independently drawn designs and eight seed pairs). Unexposed controls stay near zero, and the gain is carried mainly by the most strongly exposed probes (about +6.9). On the whole test set the effect is about +2 points. The effect is real but modest, it is not driven by near-duplicates, and seed-to-seed variation of 1–3 points is a large share of it.
