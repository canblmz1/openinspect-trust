# M3 protocol: amendments and implementation notes

[M3_PROTOCOL.md](M3_PROTOCOL.md) was committed as `8572b7e` on 2026-09-30 at 22:39, before any similarity distribution, calibration curve or leakage count had been looked at. It is kept **byte for byte as committed** (SHA-256 `d70a130babcac45d650e8f0d5227546a5266d772e5932f21f422ba98de35102e`, checked by `tests/integration/test_committed_m3.py`), so this file holds everything that was added or corrected afterwards. The protocol's own amendment log says "none yet"; that is deliberate, because editing the frozen file, even to append a row, would break the check that it is unchanged.

No amendment below changes a rule of the protocol: the pools, the precision targets, the synthetic transforms, the threshold rule, the categories, the chaining rule, the seeds and the vocabulary are exactly as frozen. Items A1 to A4 correct the implementation; items N1 to N5 record how a sentence of the protocol was made concrete.

## Timeline

| when (2026-09-30) | what |
|---|---|
| 22:39 | protocol committed (`8572b7e`) |
| 22:49 | the rule and its building blocks committed (`d844365`: `thresholds.py`, `calibrate.py`, `leakage.py`, …); CI green |
| 23:00–23:07 | A1–A3 found by reading and testing the committed code, fixed with regression tests; the synthetic copies computed (`dedup synthetic`, 3,300 pairs, 515 s) |
| 23:12 | **first end-to-end run** of the finished pipeline on the real data, written outside the repository to check scale and the report layout. Its thresholds and counts were seen from this point on. |
| after 23:12 | A4 and the reporting additions listed under A4; none of them changes a threshold, a count or any number that existed before |
| final run | the committed numbers, produced by `openinspect dedup run --all` on a clean tree at the commit named in every report |

## Corrections

### A1. A threshold that is a bin edge could be evaluated one bin too low (before the first run)

`calibrate.bin_of` maps a cosine to its histogram bin (width 0.0005). For decimal bin edges such as 0.9235, which are not exact in binary, `floor((t + 1) * 2000)` gave the bin below in 562 of 4,000 cases, so `metrics_at` could count the pairs of the 0.0005-wide bin under the threshold as if they were above it. The selection of thresholds was not affected (it works on bin indices), only the precision, recall and F1 printed at a threshold. Fix: a 1e-6 offset before the floor; the test `test_every_bin_edge_maps_back_to_its_own_bin` checks all 4,000 edges.

### A2. Bootstrap intervals at a coarser threshold than their estimate (before the first run)

The 95% intervals (section 5: 1,000 resamples of the positive groups, seed 0) were computed on histograms coarsened eight times (resolution 0.004), so the interval of the precision at `family` belonged to a threshold up to 0.004 lower than the point estimate next to it. The resolution is now the calibration bin width (`COARSE = 1`); the resampling itself is unchanged. Test: `test_bootstrap_intervals_refer_to_the_exact_threshold`.

### A3. A graph without edges crashed the group table (before the first run)

`graph.edge_stats_by_label` failed on an empty edge list (a source with no pair above a threshold). It now returns no statistics. Test: `test_edge_statistics_of_a_graph_without_edges_are_empty`.

### A4. The calibration table printed a fallback value under the heading of a precision target (after the first run, reporting only)

When a pool never reaches a precision target, rule 5 uses its F1-optimal cosine. `SourceThreshold` stored only the value used, so the report showed, for example, "cosine for precision 0.50: 0.7575" for `pcb-ind`, where precision 0.50 is in fact never reached, and the fallback note named only the 0.90 target. The record now keeps the raw results (`precision_050`, `precision_090`, `None` when never reached) next to the values used, and the note names every fallback. The values used and therefore the thresholds are identical; `test_the_rule_is_applied_and_the_fallback_is_recorded` covers the record.

Reporting additions made after the first run, all threshold-free descriptions that did not exist before: the share of images whose most similar image shares the source's own key, with its chance level (`Top1Stats.top1_same_group` and friends, the number M2 gave for `pcb-defect`), the cumulative distribution of the top-1 cosine for the figure, and the choice, in the performance table, of the run that did the embedding work rather than the latest run that only read the cache.

## Implementation notes

- **N1. Population precision.** Section 5 says all pairs are counted exactly; precision is therefore the precision over every pair of a source, under a strong imbalance (`pcb-ind`: about 178 negative pairs per positive). No negative sampling is used, because sampling would change the precision the rule is defined on.
- **N2. The review-level sweep** (section 8) is the percolation table: checkpoints every 0.01 from `review` up to 0.99, plus `review`, `family`, `near` and `family` ± 0.02, per source. If more than 30 million pairs lie above the lowest checkpoint, the sweep starts at the lowest checkpoint that fits and the report says so; `family` itself must always fit.
- **N3. Group ids.** Groups of the all-source graph are called `VSG-near-NNNNN` and `VSG-family-NNNNN` (visual similarity group), numbered by their smallest member in the fixed image order, so they are not confused with the `DUP-NNN` ids of a release.
- **N4. The review queue** (section 10) has about 300 pairs, split equally over strata of scope (inside one source, or across sources) and suggested category; what a small stratum cannot use goes to the others. One stratum per scope, `BELOW_REVIEW`, holds nearest-neighbour pairs the rule does not flag, so a reviewer also sees what the thresholds leave out (SPEC 7.3 asks for pairs across the whole similarity range and for hard negatives). Every pair has `decision = review` in `duplicate-pairs.parquet`; M3 decides nothing.
- **N5. Performance of the embedding runs.** The cache was filled, and the synthetic copies embedded, before the per-run record (`<data>/m3/runs/*.jsonl`) existed. Their two records were transcribed from the console logs, which are kept in `<data>/m3/logs/`; the values are exactly as printed (rounded), and each record says so in its `note`.
