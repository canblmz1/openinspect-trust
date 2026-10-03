# Representation sensitivity (DINOv2-small vs DINOv2-base) and alternative groupings

Scope: no new embeddings were computed. The analysis uses the cached DINOv2-small and DINOv2-base vectors under `C:\data\openinspect\embeddings`, `artifacts/m5_5/representation-membership.parquet`, the pHash cache, and the M3 pair table. Nothing was retrained.

## 1. The discrete groups disagree almost completely outside PCB-Defect

| source | ARI, components (small vs base) | ARI, A1 constraint groups | items that change A1 split under base |
|---|---|---|---|
| DsPCBSD+ | 0.008 | 0.003 | 34.7% |
| PCB-IND | 0.010 | 0.077 | 30.2% |
| PCB-Defect | 0.359 | 0.000 | 8.5% |
| all items | 0.506 | 0.639 | 27.4% |

Non-members are counted as singletons here, which is why the PCB-Defect value differs from the 0.287 in M5.5. The pooled ARI is high only because the PCB-Defect giant group dominates. Within DsPCBSD+ and PCB-IND the two representations produce almost unrelated components: small puts 366 and 387 items in components, base only 33 and 31.

Effect on the M7 roles (design 0, 1, 2): probes whose exposing mate shares a **base** constraint group with them are 111/194, 108/193 and 112/194, about 57%. About 43% of the probes would not count as exposed if the groups had been built from DINOv2-base.

## 2. The continuous exposure contrast is not DINO-small-specific

For every test item, take the maximum cosine to the C0 training set minus the maximum cosine to the C1 training set (`data/exposure.csv`):

| design | representation | probes: mean Δ | controls: mean Δ |
|---|---|---|---|
| D0 | small | 0.058 | 0.002 |
| D0 | base | 0.053 | 0.001 |
| D1 | small | 0.051 | 0.002 |
| D1 | base | 0.049 | 0.002 |
| D2 | small | 0.054 | 0.004 |
| D2 | base | 0.050 | 0.002 |

The swap gives probes visually closer training neighbours in C0 than in C1, and it does so to almost the same degree whichever representation measures it. The contrast between conditions is therefore real in feature space. Only the binary group boundary is fragile.

## 3. Dose-response under both representations

C0 − C1 mAP50-95 (pp), with probes binned by Δ and controls kept whole (`data/dose_response.csv`, `figures/dose_response.png`):

| design | representation | controls | probes Δ<0.02 | probes 0.02–0.08 | probes Δ>0.08 |
|---|---|---|---|---|---|
| D0 (3 seeds) | small | −0.17 | +1.37 | +1.58 | **+6.80** (6.21 / 7.91 / 6.28) |
| D0 (3 seeds) | base | −0.17 | +2.77 | +3.59 | **+6.64** (5.96 / 7.93 / 6.02) |
| D1 (1 seed) | small | +3.09 | +0.73 | +3.36 | **+7.43** |
| D1 (1 seed) | base | +3.09 | +0.79 | +0.21 | **+13.65** |
| D2 (1 seed) | small | +0.02 | +1.64 | +3.55 | **+6.69** |
| D2 (1 seed) | base | +0.02 | +3.88 | +3.50 | **+8.46** |

The most strongly exposed probes, 42–64 items per design, gain +6.6 to +13.7 pp in every design, every seed and both representations. This is the most robust result in M7. It does not depend on the DINO-small groups, because the bins can be computed from either embedding.

## 4. Which visually adjudicated pairs are stable across representations?

Of the 300 review pairs, 19 lie above the base threshold of 0.958. Visual labels of those 19: A 1, B 8, C 1, D 9. Of the 21 pairs judged A, **only 1** reaches the base threshold. Many of the A pairs are mirrored copies, which both models score below their thresholds.

| final visual label | above base threshold | below |
|---|---|---|
| A | 1 | 20 |
| B | 8 | 24 |
| C | 1 | 46 |
| D | 9 | 153 |
| E | 0 | 32 |

So "high-confidence visually valid" pairs are **not** more representation-stable at the calibrated thresholds. Base is simply far more conservative. Under DINOv2-small, cosine ≥ 0.96 picked out 9 of 11 pairs as A+B. That is the only score band that is reliably duplicate-like.

## 5. Alternative groupings (pHash, exact SHA)

- Exact SHA-256: 0 identical pairs in the M3 graph (`sha256_equal` is all False). An exact-hash grouping would put no constraint on any split and would expose no probe.
- pHash: as a grouping signal on its own it is weak. pairs at distance 0–4 are only 22% A+B, while 5–10 is 86% A+B (n = 7). The REVIEW_REQUIRED stratum (pHash-only) is 0% related in DsPCBSD+ and cross-source.
- Retraining under alternative groupings was out of scope (no training). The answer here therefore comes from feature-space contrast and visual review, not from a re-run of the experiment.

## Answer: does the M7 conclusion depend heavily on DINO-small?

- **Which items are probes:** yes. About 43% of probes would lose their exposure label under base groups, and the components barely overlap within DsPCBSD+ and PCB-IND.
- **That exposed test items gain:** no. The C0/C1 swap moves the nearest-neighbour similarity of probes by the same amount under base, and the dose-response gradient holds under both embeddings.
- **What the exposure *is*:** this is not settled by either representation. Visually the exposing mates are mostly same-family, not duplicates (see `PROBE_CONTROL_CONFOUND_AUDIT.md`).
