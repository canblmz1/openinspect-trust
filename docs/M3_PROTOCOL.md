# M3 protocol: duplicate, near-duplicate and leakage-group audit

Written on 2026-09-30, **before any leakage number was computed**. The embeddings existed when this was written, but no similarity distribution, calibration curve or leakage count had been looked at. Rules below are fixed; an amendment is appended to the log at the end with the reason and the date, never edited in place.

## 1. Question

> How common is it, in the official or random splits of the three accepted sources, for visually very similar images to sit on both sides of a split boundary, and can such images be grouped reliably?

The answer may be "rarely", and that is a valid result. Nothing in this protocol is tuned towards a particular answer.

## 2. Vocabulary (binding for every report)

* A **visual similarity group** (or **potential leakage group**) is a connected component of image pairs whose embedding similarity reaches a threshold.
* Visual similarity is **not** proof of "the same physical board". The word "board" is used only for what a source's own metadata says (for example a production batch), never for a similarity group.
* `EXACT_DUPLICATE` (identical bytes) is the only certain category. `NEAR_DUPLICATE`, `SAME_FAMILY_OR_SCENE` and `REVIEW_REQUIRED` are suggestions to a human reviewer, not verdicts.
* **No image is deleted, excluded or re-labelled in M3.** The milestone detects, groups, reports and prepares review. What to do with a group is a later decision.

## 3. Inputs

The 15,278 images of `dspcbsd-plus` (10,259), `pcb-ind` (4,789) and `pcb-defect` (230) as ingested in M2: file bytes verified against the recorded SHA-256 at read time, original split (`train`/`val` for DsPCBSD+, `train`/`val`/`test` for PCB-IND, none for PCB-Defect), and the grouping keys M2 found (`pcb-ind`: batch and (batch, side); `pcb-defect`: design family A and (A, B); `dspcbsd-plus`: none).

## 4. Representation

* **Hashes.** SHA-256 of the file bytes; 64-bit pHash (grayscale 32x32, 2-D DCT, the 8x8 low-frequency block against its median); the 64-bit dHash computed at ingest.
* **Embedding.** DINOv2-small (`facebook/dinov2-small`, revision `ed25f3a3...`, weights SHA-256 verified), the final-layer CLS token, L2-normalised. Preprocessing version `v1`: the whole image (no crop) resized to 224x224 with bicubic interpolation, ImageNet mean and standard deviation. Backend `cpu-fp32`. A second model (DINOv2-base) may be run as a robustness check; its results are reported separately and never mixed with the first.
* **Cache.** One vector per image, keyed by image SHA-256, model id and revision, preprocessing version and backend.
* **Similarity.** Exact cosine on all pairs (no approximate index: 15,278 vectors cost seconds, and an approximation would put search error into the calibration).

## 5. Calibration

All pairs of a source are counted exactly; the pools are:

| source | positive pairs | negative pairs | ignored |
|---|---|---|---|
| `pcb-ind` | same (batch, side) | different batch | same batch, other side |
| `pcb-defect`, family pool (used by the rule) | same design family A | different A | none |
| `pcb-defect`, strict pool (informational) | same (A, B) | different A | same A, other B |
| `dspcbsd-plus` | not used: no group key | not used | everything |

Pair labels are noisy in both directions (two images of one batch can look nothing alike, and two batches can carry one design), so the results are **group-label agreement**, not accuracy. For each pool the report gives ROC AUC, average precision, precision, recall, F1 and false-positive rate over a grid of thresholds, and the same for the pHash and dHash distances as baselines. 95% intervals come from resampling the positive groups with replacement (1,000 resamples, seed 0; the negative pairs stay fixed).

**Synthetic positives.** For a seeded sample of 100 images per source (seed 0), each image is paired with its own transformed copies: JPEG re-encoding at quality 75 and 40, brightness and contrast x1.15 and x0.85, Gaussian blur of about one pixel at the 224-pixel model scale, a half-size down-and-up resample, and crops keeping 95% and 90% of each side at a seeded offset. These ten transforms form the *near-duplicate set*. A crop keeping 80% per side is reported as *partial overlap* and is not part of the set.

## 6. Threshold rule

Applied mechanically by `openinspect.dedup.thresholds.select_thresholds`:

1. `family`: per labelled pool (`pcb-ind`, `pcb-defect` family), the lowest cosine whose precision stays at or above **0.90** from the top of the ranking, ignoring thresholds with fewer than 50 pairs above them. The operating value is the **maximum over the two pools**, so the target holds wherever it was measured.
2. `review`: the same with precision **0.50** (more likely than not the same group), capped at `family`.
3. `near`: the larger of `family` and the cosine that keeps **95%** of the near-duplicate set above it, taking the lowest value over the three sources (a threshold must catch the copies in every source).
4. `phash_candidate`: the Hamming distance that covers 95% of the photometric synthetic copies (largest over sources), capped at 12 bits so the candidate set stays reviewable.
5. If a pool never reaches a precision target, the F1-optimal cosine of that pool is used instead and the fallback is written into the report.

The thresholds are applied unchanged to `dspcbsd-plus`. How they behave there (distribution of nearest-neighbour similarity against the labelled sources, share of images above each threshold) is reported as transfer behaviour, not as validation.

## 7. Categories

| category | rule |
|---|---|
| `EXACT_DUPLICATE` | identical SHA-256 |
| `NEAR_DUPLICATE` | cosine >= `near` |
| `SAME_FAMILY_OR_SCENE` | `family` <= cosine < `near` |
| `REVIEW_REQUIRED` | `review` <= cosine < `family`, or a pHash distance <= `phash_candidate` with cosine < `review` (hash and embedding disagree) |

## 8. Graph and leakage numbers

* Nodes are images; edges are pairs with cosine >= the level threshold; groups are connected components. Two levels: `near` and `family`; a `review`-level sweep is reported for sensitivity.
* **Per-source numbers** (M3F) come from the graph *within* each source: groups, singletons, groups crossing train|val, train|test, val|test, affected images and annotations, and the share of validation and test images with a direct neighbour at or above the threshold in train. A second, threshold-free number is the distribution of each evaluation image's highest cosine to any training image.
* **The groups table** (`leakage-groups.parquet`) comes from the graph over *all* sources, so a group that links two sources is visible (`cross_source`). Every group stores the statistics of all its member pairs (maximum, minimum, mean), next to the edge statistics, because components chain.
* **Chaining rule.** If the largest `family`-level group of a source holds more than 25% of its images, the source is flagged; its `near`-level numbers are then the primary, conservative ones, and the `family`-level numbers are reported with the flag. A percolation table (groups and largest group as the threshold drops) is always given.
* **Overlap with the source's own key** (`pcb-ind`, `pcb-defect`): pair precision and recall, adjusted Rand index, homogeneity and completeness of the similarity groups against the batch and (batch, side) (or A and (A, B)) partitions; the mix of similar pairs (same subgroup, same group other subgroup, other group); and, for `pcb-ind`, how many images sit in a cross-split similarity group and/or in a batch that spans splits.
* **Random-split baseline.** The observed number of cross-split groups is compared with the same groups under 1,000 random re-assignments of the split labels keeping the split sizes (seed 0). If the observed count is close to the random expectation, the split behaves as if it ignored visual similarity.
* **Reconstructed group-aware split** (seed 0, official split sizes): whole groups are assigned to splits. Its cross-split count is *measured*, not assumed, and the highest-cosine-to-train distribution is compared with the official split's.

## 9. `dspcbsd-plus` (no group key)

Whether embedding clusters form a meaningful latent grouping is judged by: (a) group cohesion (minimum and mean pairwise cosine of the members, chaining share); (b) stability (agreement between the partitions at `family` and at `family` +/- 0.02); (c) agreement with pHash near-duplicates; (d) transfer of the calibrated thresholds (section 6); (e) agreement with the second model if it is run; (f) a qualitative look at a seeded random sample of groups. None of this is ground truth, and the report says so.

## 10. Review pack

A seeded, stratified queue of about 300 pairs (the D9 budget) is written as `review-candidates.csv` and as a local HTML contact sheet with both images, similarity, hash distance, source, split, group keys and the machine's suggested category. A reviewer's decision column stays empty until a human fills it.

## 11. Reported with every result

Images per second, embedding cache size, peak memory and total runtime; the number of images that failed to read or decode (never deleted); the model, revision, preprocessing version and backend; the commit of the code that produced the numbers.

## Amendment log

| date | change | reason |
|---|---|---|
| 2026-09-30 | none yet | first version |
