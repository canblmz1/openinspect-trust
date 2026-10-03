# Final claim register: frozen for publication (3 October 2026)

**AI visual adjudication was performed on the prepared review pairs. Independent human validation was not performed.**

This table is the authoritative claim policy for the paper, the README and all briefs. No statement may go beyond it.

| # | claim | status | evidence (`reports/m7_final/`) | required qualifier |
|---|---|---|---|---|
| 1 | Machine-detected group exposure is associated with higher performance on the exposed (probe) test images. | **SAFE** | Probe effect positive in 8/8 matched seed pairs (min +1.69). Pooled +3.70 (95% +1.71 to +5.70). D0 primary +3.91 (combined +0.41 to +7.65). | "machine-detected groups"; YOLO11n; this PCB benchmark |
| 2 | The pre-specified primary endpoint (D0 probe C0 − C1) is positive. | **SAFE** | +3.91; combined interval +0.41 to +7.65; P(≤0) = 0.014 | state that the seed-only interval (3 seeds) includes zero |
| 3 | The gain is selective for exposed images (probe − control). | **QUALIFIED** | Pooled +3.37 (+0.68 to +6.06). Placebo p = 0.013 (D0), 0.009 (D1), 0.078 (D2). D0 alone: −0.97 to +9.07 | "on average across designs"; D0's own interval includes zero; two of eight seed pairs show about 0 |
| 4 | D0 replicates across seeds. | **QUALIFIED** | Probes positive in 3/3 seeds (+3.65, +6.34, +1.74); probe − control +0.28 in seed 2 | name seed 2 |
| 5 | D1 replicates D0. | **QUALIFIED** | After 3 seeds: probe +4.03, control +0.22, probe − control +3.81, placebo p = 0.009. Seed 0 control +3.09 did not recur | report seed 0's control anomaly; "training stochasticity is plausible, not proven" |
| 6 | D2 replicates D0. | **DO NOT CLAIM** as a success | Seed 1: probe +1.69 = control +1.68; placebo p = 0.078; interval includes zero | say "mixed replication across D2 seeds" |
| 7 | Gains are concentrated among the most strongly exposed probes. | **SAFE** (wording fixed) | Δ > 0.08 stratum +6.85, 8/8 seed pairs positive (min +4.52), including the 3 pairs trained after the strata were fixed; also under DINOv2-base | say the strata were defined after the first five seed pairs were evaluated |
| 8 | Performance gain increases with similarity / similarity predicts gain. | **DO NOT CLAIM** | Continuous Spearman 0.08–0.15; only D0-small excludes zero | allowed: "the strongest pre-defined exposure stratum consistently showed the largest difference, while the continuous relationship was weak" |
| 9 | Group exposure makes the whole benchmark modestly optimistic. | **SAFE** | D0 overall +1.76; pooled +2.03 (+0.79 to +3.27) | "modestly", "about 2 points" |
| 10 | Near-duplicate leakage / duplicate memorisation explains the effect. | **DO NOT CLAIM** | 0/60 probe–mate pairs are near-duplicates (AI adjudication) | none: do not use these terms for the M7 manipulation |
| 11 | Same-board leakage / same-board exposure causes the largest gain. | **DO NOT CLAIM** | 14/20 board-ID-linked probe→mate pairs visually unrelated; 2 overlap. Pre-planned split: metadata-only probes +11.31 in D0 but +2.39 (D1) and +0.41 (D2); visually linked probes positive in 8/8 seed pairs | board ID may be described only as source metadata |
| 12 | Causal language ("exposure caused the gain"). | **QUALIFIED** | Randomised design with a matched swap on one fixed test set | only "the controlled swap increased mAP on exposed images, in this setup (YOLO11n, these datasets, 2–3 seeds per design)"; never "near-duplicates cause" |
| 13 | Source shift is much larger than the group-exposure effect. | **SAFE** | −27.4 / −37.7 / −47.3 points vs about +2 overall | "acquisition/source shift"; one seed per source model |
| 14 | The detector cannot generalise to unseen defect semantics / PCB-Defect is intrinsically harder. | **DO NOT CLAIM** | Classes are shared; source is identifiable at 100% from size and format; an in-distribution model scores 47.6 on PCB-Defect | "these datasets encode strong acquisition/source signatures" |
| 15 | Results indicate deployment / production-line performance. | **DO NOT CLAIM** | public-dataset crops only | none |
| 16 | Human-validated, human-confirmed or expert-validated relationships; "confirmed leakage". | **DO NOT CLAIM** | no human review | "AI visual adjudication; independent human validation not performed" |
| 17 | Cross-source machine similarity links are meaningful. | **DO NOT CLAIM** | 0/66 cross-source pairs duplicate-like; B-natural did not help | none |
| 18 | EVREN relevance: the study was trained on EVREN, and identically configured EVREN runs differed by 1–2 points on subsets. | **SAFE** (factual) | replicate pairs: 1.13 overall, 2.22 on controls | do **not** claim EVREN requested, endorsed or will adopt anything; suggested platform features are "potential capabilities suggested by this case study" |
| 19 | Novelty ("first study of …"). | **DO NOT CLAIM** | search was not exhaustive | "we did not identify prior work combining these elements in this setting" |

## Terminology (frozen)

- **Primary term:** *train–test group exposure*. Long form: *machine-detected visual-similarity group exposure*.
- **"Group leakage":** only when defined as a group-level train/test dependency analogous to patient or specimen leakage, and never with "near-duplicate", "duplicate", "same-board", "confirmed" or "memorisation".
