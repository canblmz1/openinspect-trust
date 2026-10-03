# Placebo and randomisation tests (no retraining)

> **Pre-replication record, superseded 2026-10-03.** The final numbers are in `reports/m7_final/` (5 replication runs added; the analysis was re-run with 2,000 bootstrap draws and 10,000 placebo relabellings, so intervals differ from those below). Do not cite numbers from this file; see `reports/m7_final/FINAL_SCIENTIFIC_VERDICT.md`.

Question: is the observed probe − control contrast special, or would *any* split of the same test set into two parts of the same size show a gap this large, given these trained models?

Method (`scripts/stats.py` §4): keep the trained C0/C1 models and their per-image detections fixed. Redraw fake "probes" as whole A1 constraint groups taken in random order until the real probe count is reached. The source-stratified variant also matches the probe count per source. Everything else in the test set becomes fake "controls". Then recompute C0 − C1 on each part and take the difference, averaged over seeds where there are several. 2,000 placebos per design.

| design | variant | observed probe − control (pp) | null mean | null SD | null 95% range | one-sided p | two-sided p |
|---|---|---|---|---|---|---|---|
| D0 (mean of 3 seeds) | cluster, random | +4.08 | −0.02 | 1.95 | −3.81 to +3.53 | 0.013 | 0.031 |
| D0 (mean of 3 seeds) | cluster, source-stratified | +4.08 | +0.06 | 1.84 | −3.55 to +3.51 | **0.009** | 0.020 |
| D1 (1 seed) | cluster, source-stratified | +0.84 | −0.08 | 2.27 | −4.49 to +4.39 | 0.35 | 0.72 |
| D2 (1 seed) | cluster, source-stratified | +4.58 | +0.05 | 1.95 | −3.72 to +3.91 | **0.008** | 0.019 |

`figures/placebo_d0.png` shows the D0 null distribution with the observed value.

## Reading

- D0 and D2 both fall above the 99th percentile of their placebo distributions. The probe/control split is not an arbitrary partition: under the same models, the specific items whose group-mates were swapped in are the ones that improved.
- D1 is indistinguishable from placebo. Its overall C0 − C1 gain (+3.70 pp) is spread across the whole test set.
- The null SD of a placebo contrast (~1.9 pp) is about half the observed D0 effect. Single-design evidence is therefore roughly a "2-sigma" result, and the strength comes from D0 and D2 agreeing.
- These placebos condition on the trained models and permute only the test-side labels. They do not capture training-seed variation (see `STATISTICAL_RED_TEAM.md`). They answer "is the probe set special?", not "would another training run reproduce this?".
- Exposure strength works as an internal placebo: probes with a weak feature-space exposure (Δ < 0.02, n = 69 in D0) gain +1.37 pp, close to the controls, while strongly exposed probes gain +6.8 pp (`REPRESENTATION_SENSITIVITY.md` §3).
