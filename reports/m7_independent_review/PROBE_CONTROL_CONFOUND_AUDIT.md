# Probe/control confound audit

Data: frozen manifests, release items and annotations, and the per-image detections in `C:\data\openinspect\m7\eval`. The detections were checked against an independent Ultralytics re-run (see `STATISTICAL_RED_TEAM.md` §0). Scripts: `scripts/design_check.py` and `scripts/confound.py`.

## 1. Integrity of the controlled design: PASS

All three designs pass every check (`data/design_check.json`):

| check | D0 | D1 | D2 |
|---|---|---|---|
| C0 test = C1 test (IDs) | 407 = 407 | 408 = 408 | 409 = 409 |
| test = probes ∪ controls | 194 + 213 | 193 + 215 | 194 + 215 |
| package test files (images + labels) byte-identical C0 vs C1 | yes (814 files) | yes (816) | yes (818) |
| package val files byte-identical | yes (1,396) | yes (1,398) | yes (1,396) |
| train C0 \ C1 = mates; C1 \ C0 = replacements | yes / yes | yes / yes | yes / yes |
| common training files byte-identical | yes | yes | yes |
| test images match release SHA-256 | 0 mismatches | 0 | 0 |
| probes whose A1 constraint group is in C0 train / C1 train | 194 / 0 | 193 / 0 | 194 / 0 |
| controls whose constraint group is in C0 train / C1 train | 0 / 0 | 0 / 0 | 0 / 0 |
| replacements whose group touches test or val | 0 | 0 | 0 |

Replacement profile, mates vs replacements, D0: identical source counts (97 / 95 / 21) and file formats (192 jpg, 21 png). Boxes 278 vs 263, i.e. C0 has 15 more boxes: short +6, open +5, spurious +4. Median relative box area 0.0099 vs 0.0095. The same pattern holds in D1 and D2: C0 has 10 more boxes in each (268 vs 258 and 265 vs 255), with a small surplus of short and open boxes. The swap is close to clean, with one small systematic difference: **C0 always trains on about 4–6% more boxes, weighted toward short and open.**

## 2. Can probe/control identity be predicted from trivial metadata?

Random-forest 5-fold CV AUC:

| features | D0 | D1 | D2 |
|---|---|---|---|
| source, width, height, aspect, format, boxes, file bytes, box sizes, per-class counts | 0.57 | 0.60 | 0.61 |
| + constraint-group size | **0.98** | 0.97 | 0.98 |

Without group size, probes and controls are only weakly distinguishable. With group size they are almost perfectly separable, by construction: probes come from groups (median size 7), and 141 of 213 D0 controls are singletons. So **probe vs control is mostly "in a group" vs "a singleton"**. Any difference correlated with "belonging to a dense visual cluster" can therefore masquerade as an exposure effect. This is the main design-level confound. The C0 − C1 contrast is computed within each subset, which removes level differences but not interactions between "grouped" and "training changes".

A partial check is possible because some controls are grouped. D0 grouped controls (72) moved −0.99 pp and singleton controls (141) +0.50 pp. Grouped items that were *not* exposed did not gain, which argues against a pure "dense-cluster" artefact. D1 does not fit this pattern: singleton controls +5.67, grouped +2.64.

## 3. Composition differences, probes vs controls (D0)

| | probes | controls |
|---|---|---|
| DsPCBSD+ / PCB-Defect / PCB-IND | 88 / 20 / 86 | 89 / 39 / 85 |
| boxes per image | 1.24 | 1.22 |
| boxes short / open / mouse_bite / spurious | 35 / 47 / 90 / 68 | 23 / 38 / 104 / 95 |
| png share | 10% | 18% |
| median relative box area | 0.0091 | 0.0111 |

Controls hold twice as much PCB-Defect and fewer short boxes. Those are exactly the cells with the largest gain among probes: short +8.2 pp in every seed (10.4 / 9.9 / 4.1); control short −0.5.

## 4. Can per-image gain be explained by source or class instead of exposure?

Outcome: per-image recall gain (C0 − C1, conf ≥ 0.25, averaged over IoU 0.50–0.95, mean of 3 seeds). OLS with standard errors clustered by constraint group, n = 407. R² is low throughout (≤ 0.06): per-image recall is noisy.

| model | probe (or exposure) coefficient | p |
|---|---|---|
| gain ~ probe | +0.044 | 0.005 |
| + source, boxes, log box area, class counts, max sim to C1 train | +0.043 | 0.002 |
| gain ~ exposure Δ (cosine) + covariates | +0.53 per unit Δ (≈ +0.05 at Δ = 0.1) | 0.0005 |

Covariates: n_short +0.036 (p 0.02); max similarity to C1 train −0.33 (p 0.006): items that are already close to C1 training data gain less. The covariates do not absorb the probe effect, and the continuous exposure measure predicts gain better than the probe label.

The probe × source model is the reason for caution. The probe effect is concentrated in PCB-IND (interaction +0.061, p 0.08) and PCB-Defect (+0.031, p 0.03). DsPCBSD+ probes alone show +0.012 (p 0.40) on this per-image measure, although their subset mAP gain is +3.8 pp.

## 5. What the probes are actually exposed to (targeted visual check)

60 D0 probes were drawn in strata by link type. For each, the nearest exposing mate was shown blinded, together with 30 controls and their nearest C0-train image (`data/probe_mate_review.csv`). **AI visual adjudication; not human validation.**

| link type (n shown) | A | B | C | D | E | subset gain D0 (pp) |
|---|---|---|---|---|---|---|
| crop sibling (12) | 0 | 1 | 11 | 0 | 0 | +0.87 (−3.0, 7.8, −2.2) |
| similar pair (16) | 1 | 1 | 11 | 3 | 0 | +4.73 (3.3, 6.7, 4.2) |
| same component (12) | 0 | 0 | 12 | 0 | 0 | +2.17 (3.1, 1.0, 2.4) |
| same metadata group (20, all PCB-IND) | 0 | 2 | 2 | 11 | 5 | **+11.31** (15.6, 12.2, 6.2) |
| control → nearest C0-train (30) | 0 | 2 | 14 | 9 | 5 | −0.17 |

Only **5 of 60 (8%)** probe–mate pairs look duplicate-like (A/B). 83% look at least same-family. The PCB-IND metadata-group probes carry the largest gain, and their mates are other crops of the same board ID or batch (e.g. `6331_b_*`). Most of those crops look like *different regions* (16/20 D/E). Whatever the model gains there is not memorisation of a near-duplicate. The more plausible mechanism is shared acquisition and board appearance: substrate colour, trace width, illumination.

## 6. Verdict on confounders

- Ruled out as the main explanation: source mix, image size and format, class mix, box count (all balanced or controlled for), accidental exposure of controls (0 by constraint group; feature-space Δ ≈ 0), and replacement artefacts (no replacement touches test or val).
- Remaining confounds:
  1. probe = grouped vs control = singleton, partly addressed by the grouped-control check in D0 but contradicted in D1;
  2. C0 has 4–6% more training boxes, weighted to short and open;
  3. the effect is concentrated in a handful of strata (PCB-IND metadata groups, the short class), each with tens of boxes, so small-sample noise is large.
- The interpretation must change from "near-duplicate leakage" to **"exposure to same-family / same-board group-mates"**. That is still leakage in the sense of patient-level leakage, but the claim is different from the one the word "near-duplicate" suggests.
