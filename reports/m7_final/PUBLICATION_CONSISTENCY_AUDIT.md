# Publication consistency audit (3 October 2026)

**Scope.** Every number in `paper/`, `README.md` and `reports/m7_final/*.md` was cross-checked against the frozen CSVs:

- `FINAL_REPLICATION_TABLE.csv`, `FINAL_SEED_AWARE_STATS.csv`, `FINAL_PLACEBO_RESULTS.csv`, `FINAL_DOSE_RESPONSE.csv`;
- source shift from the M7 per-image evaluation, reproduced by two evaluators;
- visual-review counts from `reports/m7_independent_review/AI_PM_ADJUDICATED.csv`.

## 1. Re-verification of the frozen analysis

The final analysis was re-run from the sanitised public scripts, which now use environment-variable paths and neutral replicate aliases instead of local paths and job-ID fragments:

- bootstrap, placebo, dose-response and visual-category outputs: **identical** (maximum absolute difference 0.0; the three placebo null arrays are identical);
- replication table: identical up to the old 3-decimal storage rounding (≤ 0.0005).

The re-run outputs were installed as the frozen version, now stored at 6 decimals, so that all rounding to 2 decimals is done from full precision. Nothing scientific changed.

**Automated check.** `paper/scripts/audit_numbers.py` parses manuscript Tables 1–3 and compares every cell with the CSVs, and scans the public text for known stale values. Final run: **ALL CHECKED NUMBERS MATCH; no stale values found.**

## 2. Corrections made

| # | where | before | after | reason |
|---|---|---|---|---|
| 1 | manuscript Table 1, D0 seed 1, probe − control; `FINAL_GROUP_EXPOSURE_RESULT.md` (row and min/max) | +7.74 | **+7.73** | exact 7.7347; the earlier value was rounded from a 3-decimal intermediate (7.735) |
| 2 | `FINAL_GROUP_EXPOSURE_RESULT.md`, D0 overall interval A | +0.20 to +3.77 | **+0.20 to +3.76** | exact upper bound 3.7648 |
| 3 | `FINAL_GROUP_EXPOSURE_RESULT.md`, D1 probe − control interval B | −3.32 to +10.94 | **−3.31 to +10.94** | exact −3.3146 |
| 4 | `FINAL_GROUP_EXPOSURE_RESULT.md`, D2 placebo one-sided p | 0.079 | **0.078** | exact 0.0785 |
| 5 | `FINAL_GROUP_EXPOSURE_RESULT.md`, base Spearman for D2 | +0.11 | **+0.10** | exact 0.105 |
| 6 | `FINAL_GROUP_EXPOSURE_RESULT.md` §Exposure strength | "bins fixed before the 5 new runs; those 5 runs are out-of-sample" | "fixed after five seed pairs were evaluated; the **three seed pairs** completed by the new runs are out-of-sample; binning is post hoc for the first five" | the 5 runs formed 3 new pairs (one D1 C0 member pre-existed); post-hoc status was not stated |
| 7 | first draft of the manuscript, Δ < 0.02 stratum mean | +0.03 | **+0.00** | exact mean 0.004 |
| 8 | manuscript draft, `FINAL_SOURCE_SHIFT_RESULT.md`, `README.md` | PCB-Defect described as "flatbed scans", "DIY" or "hobby" boards | "high-resolution images of laboratory-fabricated single-layer FR4 boards" | the source paper (Rashid et al. 2025) does not say "flatbed" or "DIY" |
| 9 | `FINAL_D1_DIAGNOSIS.md`, `FINAL_SCIENTIFIC_VERDICT.md`, `FINAL_EXECUTIVE_SUMMARY_TR.md` | D1 anomaly "best explained as / was" training stochasticity; "D1 now replicates" | "did not recur; training stochasticity is plausible but unproven" | claim policy |
| 10 | `FINAL_D1_DIAGNOSIS.md`, `final_analysis.py`, replication CSV | replicate referred to by job-ID fragments | aliases r1 / r2 | public safety |
| 11 | `FINAL_SCIENTIFIC_VERDICT.md` | referenced `FINAL_RUN_INVENTORY.csv` and `checkpoint_manifest_replication.csv` (private) | references the public ID-free versions in `public/` | public safety |
| 12 | manuscript abstract | 330 words (> arXiv's 1,920 characters) | 239 words / 1,677 characters, same content | arXiv and workshop limits |
| 13 | manuscript references | Robust AD cited as CVPR | CVPR **Workshops** (VAND) | verified on CVF open access |
| 14 | manuscript related work | none | Figueiredo & Mendes (IEEE Access 2024) added | verified closest group-leakage work in object detection |
| 15 | `README.md` | "No model has been trained yet"; "M7 plan … not executed" | status updated; short Research-finding section added | stale |
| 16 | `reports/m7/final_results.md` and 5 pre-replication independent-review reports | no notice | "Pre-replication record, superseded" banner | stale intervals (e.g. −0.68 to +8.46; D1 placebo 0.35) remain only as dated records |
| 17 | paper Figure 2 | footnote clipped at the edges | regenerated | readability |
| 18 | paper Figure 1 | no sample sizes, no interval statement | n per stratum on the axis; "no interval shown" stated | figure standards |
| 19 | manuscript Section 8 | the pre-planned split of probes by link type (from the M7 analysis plan committed before training) was not reported | added as Table 5 and in `FINAL_GROUP_EXPOSURE_RESULT.md` (`probe_link_split.csv`) | completeness of pre-specified analyses |
| 20 | manuscript methods | pooling assumption not stated | fixed-effect assumption and possible under-coverage stated | statistical transparency |
| 21 | paper tables | standalone tables numbered like the manuscript tables but with different content | renamed to supplementary S1–S8 | avoid mis-citation |

## 3. Values confirmed (unchanged)

- **Primary endpoint:** D0 probe +3.91; intervals A +1.27 / +6.77, B −1.82 / +9.64, C **+0.41 / +7.65**; P(≤0) = 0.014.
- **D0:** overall +1.76; probe − control +4.08 (C −0.97 / +9.07).
- **Pooled:** probe +3.70 (+1.71 / +5.70); probe − control +3.37 (+0.68 / +6.06); overall +2.03 (+0.79 / +3.27).
- **Probe sign:** positive in 8/8 seed pairs (minimum +1.69). Control mean +0.23 (range −1.68 / +3.09).
- **Placebo, one-sided:** D0 0.013, D1 0.009, D2 0.078 (10,000 relabellings).
- **Strongest exposure stratum:** mean +6.85, minimum +4.52, 8/8 positive. New pairs +10.01, +5.71, +4.52.
- **Continuous Spearman:** 0.08–0.15.
- **Source shift:** 43.74 → 16.37, 56.82 → 19.17, 47.62 → 0.33.
- **Visual review:** 0/60 near-duplicates; 4 / 9 / 28 / 16 / 3; κ 0.17.

## 4. Files that legitimately keep superseded numbers

Each carries a banner: `reports/m7/final_results.md` and `reports/m7_independent_review/{INDEPENDENT_VERDICT, STATISTICAL_RED_TEAM, PLACEBO_TESTS, D1_INVESTIGATION, REVIEWER_2_REPORT}.md`. They are dated records of the pre-replication state and must not be cited.
