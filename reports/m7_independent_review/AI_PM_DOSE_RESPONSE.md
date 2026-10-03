# Probe–mate review: visual relationship vs similarity and vs gain

Visual labels were frozen (adjudicated) before any score was unblinded. Bins follow the existing project conventions:

- **M3 cosine bands** (DINOv2-small, `artifacts/m3/thresholds.json`): below family < 0.918 ≤ family band < 0.934 ≤ near band.
- **Exposure-Δ bins** from the M7 independent review (`REPRESENTATION_SENSITIVITY.md`): the probe's maximum cosine to C0 train minus its maximum cosine to C1 train, binned < 0.02 / 0.02–0.08 / > 0.08.

Nothing was retrained. Gains come from the stored per-image detections of the three D0 seed pairs.

## Phase 8: does DINO similarity track visual relationship?

Probe pairs, by the cosine of probe to shown mate:

| M3 band | n | A | B | C | D | E/F | G |
|---|---|---|---|---|---|---|---|
| < 0.918 (below family) | 32 | 0% | 6% | 3% | 41% | 44% | 6% |
| 0.918–0.934 (family band) | 8 | 0% | 25% | 38% | 0% | 25% | 12% |
| ≥ 0.934 (near band) | 20 | **0%** | 0% | 25% | 75% | **0%** | 0% |

Probe pairs, by exposure Δ:

| Δ bin | n | A | B | C | D | E/F | G |
|---|---|---|---|---|---|---|---|
| < 0.02 | 21 | 0% | 5% | 5% | 29% | **57%** | 5% |
| 0.02–0.08 | 22 | 0% | 5% | 18% | 50% | 18% | 9% |
| > 0.08 | 17 | 0% | 12% | 24% | 65% | **0%** | 0% |

All 90 pairs, by cosine: below family 48% E/F; family band 12%; near band 0%.

Spearman correlation of ordinal visual strength (B > C > D > E, G excluded) with cosine: ρ = 0.59 for all 90 (p < 10⁻⁸) and 0.49 for probes (p = 0.0001). With exposure Δ: ρ = 0.52 (p < 10⁻⁴).

**Answer:** yes, higher DINO similarity goes with more meaningful visual relationships. Nothing in the near band or above Δ 0.08 was unrelated, and most low-similarity pairs were. But **the near band does not mean "near-duplicate"**: 0 of 20 near-band pairs were duplicates, and 75% were only structurally similar. DINO similarity measures family or structural resemblance, not specimen identity.

## Phase 9: does visual relationship track the C0 − C1 gain?

D0 subset mAP50-95 gain (C0 − C1, pp) for the probes in each visual category. These are tiny subsets, so per-seed values are shown.

| visual category of probe → mate | probes | boxes | seed 0 / 1 / 2 | mean | mean per-image recall gain | mean Δ |
|---|---|---|---|---|---|---|
| A/B (same-instance-like) | 4 | 5 | +5.8 / −17.8 / +12.4 | +0.1 | **+0.21** | 0.103 |
| C (same design) | 9 | 10 | +6.9 / +2.4 / +2.0 | **+3.8** | +0.03 | 0.096 |
| D (structural) | 28 | 32 | +1.8 / +4.9 / −0.7 | +2.0 | +0.01 | 0.057 |
| E/F (not related) | 16 | 16 | +0.4 / +9.9 / −11.1 | −0.3 | **−0.02** | 0.011 |
| G (ambiguous) | 3 | 4 | +4.7 / +4.9 / +0.4 | +3.4 | +0.02 | 0.032 |

Spearman correlation of visual strength with per-image recall gain (probes): ρ = 0.19, p = 0.16.

The ordering is monotone in the per-image recall gain (B > C > D > E) and nearly monotone in subset mAP (C > D > E/F). The A/B mAP cell has 5 boxes and is meaningless. **On these 60 probes the evidence is suggestive, not significant.** Combined with the earlier exposure-Δ dose-response on all 194 probes (+6.8 pp at Δ > 0.08 in all three seeds), the picture is consistent: gain rises with the strength of the visual relationship, and probes with no visible relationship to their nearest mate gain nothing on average.

### The same-board-ID subset

| subset (20 sampled PCB-IND same-board-ID probes) | probes | seed 0 / 1 / 2 | mean | per-image recall gain |
|---|---|---|---|---|
| all 20 | 20 | +6.2 / +9.8 / +2.1 | +6.0 | +0.05 |
| visually A/B (overlapping crops) | 2 | +14.5 / −7.8 / +27.5 | +11.4 | **+0.45** |
| visually E/F/G | 16 | +2.4 / +13.3 / −11.6 | +1.4 | **−0.02** |

Within this subset the per-image gain is concentrated in the 2 probes whose mates visibly overlap. The 16 with no visible relationship show essentially zero per-image gain and wildly unstable subset mAP across seeds (+13.3 vs −11.6). With n = 2 versus 16, this is not proof. But it **does not support** "same-board-ID exposure as such causes the largest gain". The large +11.3 pp subset mean of all 83 metadata-group probes is more likely a mix of a few genuine overlaps and high seed noise on a small, short-class-heavy subset.

## Answers

- **Does visual relationship strength increase with DINO similarity?** Yes (ρ ≈ 0.5–0.6), but the top band reaches same-family, not duplicates.
- **Does it increase with the observed gain?** Directionally yes (monotone category means; ρ = 0.19 for per-image gain), but not significantly in this 60-pair sample.
- **Are the +6–7 pp high-similarity gains visually credible?** Yes as exposure to *closely related* training images: none of the Δ > 0.08 pairs were unrelated, 35% were same-design or same-instance, and 65% were structurally similar. They are **not** credible as duplicate memorisation, because none were duplicates.
