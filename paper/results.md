<!-- Generated from manuscript.md (single source of truth); do not edit separately. -->

## 7. Results

### 7.1 Group exposure and the probe/control contrast

Table 1 lists every matched seed pair; none is omitted (see also Figure 1).

**Table 1. C0 − C1 mAP50-95 (percentage points) on fixed test sets.**

| design | seed | overall | probes | controls | probes − controls |
|---|---|---|---|---|---|
| D0 | 0 | +1.75 | +3.65 | −0.56 | +4.22 |
| D0 | 1 | +2.36 | +6.34 | −1.40 | +7.73 |
| D0 | 2 | +1.16 | +1.74 | +1.46 | +0.28 |
| D1 | 0 | +3.70 | +3.94 | +3.09 | +0.84 |
| D1 | 1 | +2.91 | +5.82 | −0.75 | +6.57 |
| D1 | 2 | +0.20 | +2.34 | −1.68 | +4.02 |
| D2 | 0 | +2.69 | +4.60 | +0.02 | +4.58 |
| D2 | 1 | +1.65 | +1.69 | +1.68 | +0.01 |
| unweighted mean of 8 pairs | | +2.05 | +3.77 | +0.23 | +3.53 |

**Table 2. Design means and intervals (95%). A: test sampling; B: training seeds; C: combined.**

| estimand | seeds | mean | A | B | C | P(≤0), C |
|---|---|---|---|---|---|---|
| **D0 probes (primary)** | 3 | **+3.91** | +1.27, +6.77 | −1.82, +9.64 | **+0.41, +7.65** | 0.014 |
| D0 overall | 3 | +1.76 | +0.20, +3.76 | +0.27, +3.24 | −0.05, +3.95 | 0.030 |
| D0 probes − controls | 3 | +4.08 | +0.79, +7.29 | −5.19, +13.34 | −0.97, +9.07 | 0.066 |
| D1 probes | 3 | +4.03 | +1.59, +6.92 | −0.29, +8.36 | +0.92, +7.51 | 0.006 |
| D1 probes − controls | 3 | +3.81 | +0.84, +6.94 | −3.31, +10.94 | −0.65, +8.17 | 0.044 |
| D2 probes | 2 | +3.14 | +0.61, +5.93 | −15.37, +21.66 | −0.46, +6.51 | 0.045 |
| D2 probes − controls | 2 | +2.30 | −0.87, +5.66 | −26.75, +31.34 | −2.42, +6.76 | 0.143 |
| pooled probes (3 designs) | 8 | +3.70 | | | +1.71, +5.70 | |
| pooled probes − controls | 8 | +3.37 | | | +0.68, +6.06 | |
| pooled overall | 8 | +2.03 | | | +0.79, +3.27 | |

**Primary endpoint.** The D0 probe effect was +3.91 points, with a combined interval of +0.41 to +7.65. The seed-only interval for three seeds includes zero.

**Selectivity.** The probe effect was positive in all eight seed pairs (minimum +1.69). Control differences scattered around zero (mean +0.23; range −1.68 to +3.09). The probe-minus-control contrast was positive in all eight pairs, but close to zero in two of them (+0.28 and +0.01). Within D0 alone its combined interval includes zero.

**Benchmark-level effect.** On the whole test set the effect was modest: +1.76 points in D0 and +2.03 pooled.

### 7.2 Placebo analysis

**Table 3. Probe − control contrast against 10,000 source-stratified random relabellings of test groups.**

| design | seeds | observed | null mean (SD) | one-sided p | two-sided p |
|---|---|---|---|---|---|
| D0 | 3 | +4.08 | +0.03 (1.82) | 0.013 | 0.024 |
| D1 | 3 | +3.81 | −0.02 (1.69) | 0.009 | 0.019 |
| D2 | 2 | +2.30 | +0.03 (1.62) | 0.078 | 0.154 |

In D0 and D1 the real probe set is atypical among same-sized group partitions of the test set. In D2 it is not clearly so.

### 7.3 Exposure strength

Figure 2 stratifies probes by exposure Δ.

**Strongest stratum (Δ > 0.08; 50–64 images per design).** The mean difference was +6.85 points across the eight seed pairs (minimum +4.52). It exceeded the controls of the same design in every pair (mean excess +6.6). The three seed pairs trained after the strata were fixed followed the same pattern: +10.01 and +5.71 in D1, and +4.52 in D2.

**Weaker strata.** Probes with Δ < 0.02 differed by +0.00 on average, like controls. The middle stratum averaged +2.41.

**DINOv2-base.** With Δ measured by DINOv2-base, the strongest stratum averaged +6.64, +10.40 and +7.38 points in D0, D1 and D2.

**Continuous association.** The association between Δ and per-image recall gain was weak. Spearman ρ was 0.15 (D0; 95% CI 0.03–0.29), 0.12 (D1) and 0.08 (D2) with DINOv2-small, and 0.11–0.13 with DINOv2-base; only the first interval excludes zero.

**Reading.** The strongest pre-defined exposure stratum consistently showed the largest performance difference, while the continuous similarity–gain relationship was weak. We do not claim that gain increases smoothly with similarity.

### 7.4 What the exposing images look like

**Table 4. AI-assisted visual adjudication of 60 D0 probe → nearest-exposing-mate pairs (coarse categories; not human-validated).**

| relationship | pairs |
|---|---|
| near-exact duplicate | 0 |
| same specimen or capture series likely | 4 |
| same design / layout family | 9 |
| structurally related | 28 |
| not meaningfully related | 16 |
| ambiguous | 3 |

**What the pairs show.**

- *No near-duplicates.* None of the 60 pairs was a near-exact duplicate, including the 20 pairs with DINOv2 cosine ≥ 0.934 (the "near" level).
- *Similarity tracks family, not identity.* DINO similarity was associated with visual relatedness (ρ = 0.49), but at the level of design family rather than specimen identity.
- *Board-ID links.* Of 20 PCB-IND probes linked to their mates only by board-ID metadata, 14 had a nearest mate with no visible relationship, and 2 showed overlapping crops.
- *Earlier review.* In the earlier AI review of 300 similarity-audit candidates, none of 66 cross-source pairs was judged duplicate-like.

These observations motivate our terminology: we describe the manipulation as **train–test group exposure** to machine-detected visual-similarity groups, not as near-duplicate or same-board leakage.


## 8. Replication and Sensitivity

**D1: the control anomaly did not recur.** The first D1 seed showed a control gain of +3.09 points, almost as large as its probe gain. That pattern contradicts a purely exposure-specific effect, and it prompted two additional seeds. Their control differences were −0.75 and −1.68 (three-seed mean +0.22), while probe gains were +5.82 and +2.34. The original anomaly did not replicate. Training stochasticity is a plausible explanation, consistent with the 2.22-point control difference observed between two identically configured replicates, but it is not proven. With the other pre-existing C0 replicate for seed 1, the D1 seed-1 contrasts were probe +6.07, control +1.47 and probe − control +4.60.

**D2: mixed replication.** D2 seed 0 resembled D0 (probes +4.60, controls +0.02). The probe-selective pattern weakened in the second D2 seed: probes and controls rose by the same amount (+1.69 and +1.68). D2's probe − control interval includes zero and its placebo p-value is 0.08. We do not count D2 as a successful replication.

**Representation.** The strongest-exposure result held when Δ was measured with DINOv2-base (Section 7.3). The *membership* of probes, however, depends on the embedding (Section 4).

**Pre-planned split by link type.** The analysis plan specified a split of probes by how they are linked to their mates: *visually linked* (similarity pair, similarity component or crop sibling) versus *metadata only* (same source board ID or design family, with no similarity link).

**Table 5. C0 − C1 mAP50-95 on probes, by link type (per-seed values).**

| design | visually linked: probes | per seed | mean | metadata only: probes | per seed | mean |
|---|---|---|---|---|---|---|
| D0 | 111 | +2.75, +5.02, +1.69 | +3.15 | 83 | +15.57, +12.20, +6.16 | +11.31 |
| D1 | 116 | +4.88, +6.75, +3.04 | +4.89 | 77 | +6.57, +0.73, −0.14 | +2.39 |
| D2 | 116 | +3.89, +2.26 | +3.08 | 78 | +3.55, −2.73 | +0.41 |

- *Visually linked probes:* positive in all eight seed pairs (+1.69 to +6.75).
- *Metadata-only probes:* a large gain in D0 that did not replicate in D1 or D2.

We therefore do not attribute the effect to shared board identity.


## 9. Source-Held-Out Evaluation

**Table 6. Source-held-out evaluation (mAP50-95, one seed per model).**

| held-out source | held-out test images | in-distribution reference | source held out | difference |
|---|---|---|---|---|
| DsPCBSD+ | 1,768 | 43.74 | 16.37 | −27.4 |
| PCB-IND | 1,713 | 56.82 | 19.17 | −37.7 |
| PCB-Defect | 939 | 47.62 | 0.33 | −47.3 |

The in-distribution reference uses other test images of the same source under a model trained on all sources (Figure 3).

**Keeping cross-source links.** A variant that keeps training images machine-linked to the held-out source did not help: DsPCBSD+ 15.21 and PCB-IND 19.72.

**PCB-Defect is not an evaluation error.** On the same 93 PCB-Defect test images, a model that saw the source scores 47.62 and localises 84 of 94 ground-truth boxes, all with the correct class. The held-out model behaves differently:

- it predicts confidently (median top confidence 0.70);
- it assigns almost every prediction to spurious copper (2,373 of 2,378 at confidence ≥ 0.25);
- it boxes ordinary copper traces and pads of the laboratory-fabricated boards;
- it finds only 93 of 971 defects.

**Source identity.** Image width, height and file format alone identify the source with 100% balanced accuracy (random forest, group-aware cross-validation).

These datasets encode strong acquisition and source signatures. Source-held-out evaluation therefore measures real domain shift, but not pure defect-semantic generalisation. The results do not show that the detector cannot learn the defect classes, nor that PCB-Defect is intrinsically harder.

