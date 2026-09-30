# M3 protocol: amendments and implementation notes

[M3_PROTOCOL.md](M3_PROTOCOL.md) was committed as `8572b7e` on 2026-09-30 at 22:39, before any similarity distribution, calibration curve or leakage count had been looked at. It is kept **byte for byte as committed** (SHA-256 `d70a130babcac45d650e8f0d5227546a5266d772e5932f21f422ba98de35102e`, checked by `tests/integration/test_committed_m3.py`), so this file holds everything that was added or corrected afterwards. The protocol's own amendment log says "none yet"; that is deliberate, because editing the frozen file, even to append a row, would break the check that it is unchanged.

Each amendment states the **previous rule**, the **issue** found, the **correction**, and its **effect on interpretation**, and says whether it was made before or after results were seen. None changes the pools, the precision targets, the synthetic transforms, the threshold rule, the categories, the chaining rule, the seeds or the vocabulary; the final run is checked against the run made before the red-team review (below), and every number that existed then is unchanged.

## Timeline

| when | what |
|---|---|
| 2026-09-30 22:39 | protocol committed (`8572b7e`) |
| 22:49 | the rule and its building blocks committed (`d844365`); CI green |
| 23:00–23:07 | A1–A3 found by reading and testing the committed code and fixed; the synthetic copies computed |
| 23:12 | **first end-to-end run** on the real data (outside the repository, to check scale and layout); thresholds and counts seen from here on |
| after 23:12 | A4 and reporting additions (A4 below) |
| 23:38 and 23:42 | full runs with `openinspect dedup run --all` on `740662b` and on `7aa1b1b` (the second on a clean tree); same thresholds and counts |
| about 23:43 | an independent red-team review of the direction received; R1–R8 below implemented in response on 2026-10-01, all after the numbers above were known |
| 2026-10-01 01:14 | **final run** (finished), `openinspect dedup run --all --robustness-model dinov2-base` on a clean tree at `a030e7b` (the commit named in every report): all 7,315 values of the `7aa1b1b` audit are unchanged; the red-team additions are new fields only |

## Corrections found in the code

### A1. A bin-edge threshold could be evaluated one bin too low (before the first run)

- **Previous rule:** `calibrate.bin_of` computed `floor((t + 1) * 2000)` to find the histogram bin (width 0.0005) of a threshold.
- **Issue:** decimal edges such as 0.9235 are not exact in binary; 562 of the 4,000 edges mapped to the bin below, so the precision, recall and F1 printed at a threshold could include the 0.0005 below it. Selection was not affected (it works on bin indices).
- **Correction:** a 1e-6 offset before the floor; a test checks all 4,000 edges.
- **Effect on interpretation:** none on the thresholds; the operating points are now exactly those of the thresholds.

### A2. Bootstrap intervals at a coarser threshold than their estimate (before the first run)

- **Previous rule:** the 95% intervals (section 5) were computed on histograms coarsened eight times (resolution 0.004).
- **Issue:** the interval of the precision at `family` could belong to a threshold up to 0.004 lower than the point estimate beside it.
- **Correction:** the resolution is the calibration bin width (`COARSE = 1`); the resampling is unchanged.
- **Effect on interpretation:** intervals and estimates now refer to the same threshold.

### A3. A graph without edges crashed the group table (before the first run)

- **Previous rule:** `graph.edge_stats_by_label` assumed at least one edge.
- **Issue:** a source with no pair above a threshold stopped the run.
- **Correction:** it returns no statistics; a regression test covers it.
- **Effect on interpretation:** none.

### A4. The calibration table printed a fallback under the heading of a precision target (after the first run, reporting only)

- **Previous rule:** `SourceThreshold` stored only the value used for `review` and `family`.
- **Issue:** where rule 5 applied, the report showed, for example, "cosine for precision 0.50: 0.7575" for `pcb-ind`, although precision 0.50 is never reached there, and the fallback note named only the 0.90 target.
- **Correction:** the raw results are kept (`precision_050`, `precision_090`, `None` when never reached) beside the values used, and the note names every fallback.
- **Effect on interpretation:** the reader can see that both labelled pools fell back to the F1-optimal cosine. The values used and the thresholds are identical.

Reporting additions made at the same time, all threshold-free descriptions that did not exist before: the share of images whose most similar image shares the source's own key, with its chance level; the cumulative distribution of the top-1 cosine; and, in the performance table, the run that did the embedding work.

## Red-team review (received 2026-09-30, implemented 2026-10-01)

The review asked to reposition the project as a dataset and benchmark assurance layer (not a duplicate detector) and listed eight points for M3. All were implemented after the first results were known; none of them changes a threshold or a count that existed before.

### R1. Synthetic recall is measured, not assumed

- **Previous rule:** section 6, rule 3: `near` = the larger of `family` and the lowest per-source value that keeps 95% of that source's synthetic near-duplicates.
- **Issue:** when `family` is larger than a source's own value, the final `near` is stricter than that source's 95% threshold, so "95% synthetic recall in every source" does not follow from the rule.
- **Correction:** for every source the report and `artifacts/m3/synthetic-recall.json` give the target, the source's own threshold, the final `near`, the recall achieved at the final `near` and the number of copies. The rule is unchanged and nothing was re-tuned. A regression test builds the case `family` > synthetic threshold and checks that the lower achieved recall is reported.
- **Effect on interpretation:** the recall claim is now a measurement per source; where it falls short of the target, the report says so.

### R2. The group-aware split promises group integrity, not source integrity

- **Previous rule:** the docstring of `split_helper` said the helper tests "that no group, and no source, is ever cut by a split boundary".
- **Issue:** `group_aware_split` takes group ids and ratios only; it has no notion of a source, so it cannot keep a source whole.
- **Correction:** the documentation now states exactly that; `leave_one_source_out` is the source-integrity mechanism; a test shows a source spread over splits by the first and kept whole by the second. The behaviour is unchanged.
- **Effect on interpretation:** the reconstructed split in `split-leakage.md` keeps similarity components whole inside each source; it is not a source-held-out split.

### R3. Every component reports its chaining

- **Previous rule:** section 8 asks for the statistics of all member pairs next to the edge statistics; the groups table had the weakest edge and the member-pair minimum, mean and maximum.
- **Issue:** a large connected component can be a chain (A ~ B, B ~ C, A unlike C); nothing summarised how much.
- **Correction:** `leakage-groups.parquet` has `size`, `edge_min_similarity`, `edge_mean_similarity`, `all_pairs_min_similarity`, `all_pairs_mean_similarity`, `all_pairs_max_similarity` and `chaining_gap` = weakest edge minus weakest member pair; `source-comparison.md` gives the gap per source and level and the five largest components. The graph algorithm is unchanged.
- **Effect on interpretation:** components are called *visual similarity components* or *potential leakage groups*, never near-duplicate groups; the chaining rule of section 8 still decides the primary level.

### R4. The review queue is stratified by split and by metadata relation

- **Previous rule:** section 10: a seeded, stratified queue of about 300 pairs; strata were scope times suggested category, plus a below-threshold control (N4).
- **Issue:** the strata did not separate cross-split pairs from same-split ones, nor pairs sharing a metadata group from pairs that do not, so the review could not test exactly the cases the leakage numbers rest on.
- **Correction:** strata are scope (each source, or across sources) × the rule's band (near-duplicate, same family or scene, review, below review) × split relation (cross-split, same split, no split) × metadata relation (same group, other group, no key). Columns are `pair_id`, `source`, `image_a`, `image_b`, `split_a`, `split_b`, `cosine`, `phash_distance`, `metadata_group_a`, `metadata_group_b` (the sources' proxy keys), `machine_category`, `human_decision` and `human_notes` (empty), plus the subgroups, `dhash_distance` and the shared components.
- **Effect on interpretation:** a different seeded sample of about 300 pairs; no audit number changes. The queue is not a random sample and does not estimate rates.

### R5. A both-sides sensitivity check of the bootstrap

- **Previous rule:** section 5: resample the positive groups with replacement, keep the negative pairs fixed (1,000 resamples, seed 0). It stays the primary method.
- **Issue:** negative pairs are dependent too (all pairs between two batches move together), so fixing them may understate the uncertainty.
- **Correction:** one sensitivity check resamples the units of the pool's negative key (for example the production batch) with replacement and weights every pair by the draws of its units (the product for a pair between two units), for AUC, average precision, and precision and recall at `family`. **Criterion fixed here, before the check was run on the real data:** a both-sides interval at least 1.5 times as wide as the protocol's (or at most 1/1.5 as wide) is a material difference and is reported as a limitation.
- **Effect on interpretation:** see `threshold-calibration.md` and `limitations.md`.

### R6. One representation-robustness check

- **Previous rule:** section 4: "a second model (DINOv2-base) may be run as a robustness check; its results are reported separately and never mixed with the first"; section 9(e) lists it.
- **Issue:** the whole image is squeezed to 224x224, which throws away most pixels of the large scans; the leakage conclusions should not hang on one representation.
- **Correction:** DINOv2-base on the whole image (same preprocessing and backend), the option the protocol already names, calibrated by the same rule with its own pools and synthetic copies. A tiled high-resolution representation was not chosen: it would cost about four times the embedding time for every image while the resolution loss matters for one source of 230 images, and it would need a new preprocessing version that the protocol does not define. The comparison is of conclusions (components, crossing counts, the random-split reading, exposure of evaluation images) and of partition agreement, not of which model is better.
- **Effect on interpretation:** `representation-robustness.md` states for how many source and level pairs the random-split reading is the same.

### R7. The core knows generic keys only

- **Previous rule:** the calibration pools of section 5 and the names of the sources' keys were constants in `analysis.py`, keyed by source name.
- **Issue:** the reusable core was coupled to three datasets.
- **Correction:** `configs/dedup.yaml` has a `sources` section that maps each source's concepts onto `group_id`, `subgroup_id` and `acquisition_id` and declares its pools exactly as section 5 defines them; the image record of the audit uses the generic fields; a test checks that no string of the core names a dataset.
- **Effect on interpretation:** none on the numbers (the same pools and key names); `acquisition_id` is declared per source and feeds the source-diversity check.

### R8. A dimensional assurance report without a score

- **Previous rule:** none; the reports gave measurements only.
- **Issue:** a reader needs to know whether a benchmark split may be optimistic without an uncalibrated scalar score.
- **Correction:** `dataset-assurance.md` gives, per source and for the pool, a status per dimension (provenance, licence evidence, archive integrity, exact duplicates, visual similarity leakage, group split integrity, independent source validation, source diversity, cross-source overlap) by rules listed in the report, each with the measurements it rests on.
- **Effect on interpretation:** the statuses are policy choices stated up front, not calibrated probabilities; visual similarity can raise a warning, never a failure.

## Implementation notes

- **N1. Population precision.** Section 5 says all pairs are counted exactly; precision is the precision over every pair of a source, under a strong imbalance (`pcb-ind`: about 178 negative pairs per positive). No negative sampling is used, because sampling would change the precision the rule is defined on.
- **N2. The review-level sweep** (section 8) is the percolation table: checkpoints every 0.01 from `review` up to 0.99, plus `review`, `family`, `near` and `family` ± 0.02, per source. If more than 30 million pairs lie above the lowest checkpoint, the sweep starts at the lowest checkpoint that fits and the report says so; `family` itself must always fit.
- **N3. Component ids.** Components of the all-source graph are called `VSG-near-NNNNN` and `VSG-family-NNNNN`, numbered by their smallest member in the fixed image order, so they are not confused with the `DUP-NNN` ids of a release.
- **N4. The review queue** has about 300 pairs shared equally over its strata (R4); what a small stratum cannot use goes to the others. The `BELOW_REVIEW` band holds nearest-neighbour pairs the rule does not flag, so a reviewer also sees what the thresholds leave out. Every pair has `decision = review` in `duplicate-pairs.parquet`; M3 decides nothing.
- **N5. Performance of the embedding runs.** The cache was filled, and the synthetic copies embedded, before the per-run record (`<data>/m3/runs/*.jsonl`) existed. Their two records were transcribed from the console logs kept in `<data>/m3/logs/`, with the values as printed; each record says so in its `note`.
