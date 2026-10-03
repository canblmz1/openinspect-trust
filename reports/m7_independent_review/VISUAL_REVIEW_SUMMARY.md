# Visual review of the 300 M3 candidate pairs

**AI visual adjudication was performed on 300/300 review pairs. This is not a substitute for independent human validation.**

Reviewer: one multimodal AI model (Claude), 2–3 October 2026. "Pass A" and "Pass B" were made by the *same* model in the *same* session. They are two blinded readings, not two independent raters, so the agreement figures below are an upper bound on what two humans would reach.

## Protocol

- Source: `artifacts/m3/review-candidates.csv` (300 pairs, 35 strata: machine category × source × split relation × metadata key).
- Hidden controls mixed in: 18 synthetic transformed duplicates (positives) and 24 random pairs (12 cross-source, 12 within-source) (negatives), for 342 pairs in total. See `POSITIVE_NEGATIVE_CONTROLS.csv`.
- Rendering: contact sheets with 6 pairs each and a random 4-digit code per pair. Images were scaled to fit 380 px, and small crops were upscaled with nearest-neighbour so no detail was invented. The sheets showed no DINO score, pHash distance, source, split, stratum, or hypothesis role.
- Pass A: 57 sheets in seed-101 order. Pass B: the same 342 pairs, reshuffled (seed 202) with new codes. Pass A's file was not opened while Pass B was being labelled.
- Labels: A exact or near-exact duplicate; B likely the same scene, specimen or capture series; C likely the same design or family; D visually similar but plausibly independent; E unrelated; F ambiguous. Each label carries a confidence of HIGH, MEDIUM or LOW and a short visual rationale (`data/passA.csv`, `data/passB.csv`).
- Unblinding and adjudication: the 41 disagreements, plus 4 positive controls that a pass did not call A or B, were re-shown with both labels visible (`data/adj.csv`). Final label = the agreed label, or the adjudicated label where the passes disagreed.

## Agreement (Pass A vs Pass B)

| set | n | exact agreement | Cohen κ (6 labels) | linear-weighted κ (A–E) | κ related (ABC) vs not | κ (A+B) vs rest |
|---|---|---|---|---|---|---|
| all incl. controls | 342 | 88.0% | 0.82 | 0.88 | 0.88 | 0.91 |
| 300 candidates | 300 | 88.7% | 0.82 (bootstrap 95% CI 0.76–0.88) | 0.88 | 0.87 | 0.92 |

Disagreement matrix (rows Pass A, columns Pass B; `data/disagreement_matrix.csv`):

| A\B | A | B | C | D | E | F |
|---|---|---|---|---|---|---|
| A | 23 | 0 | 1 | 0 | 0 | 0 |
| B | 5 | 37 | 1 | 1 | 0 | 0 |
| C | 2 | 1 | 35 | 2 | 0 | 0 |
| D | 2 | 2 | 12 | 157 | 3 | 0 |
| E | 0 | 0 | 0 | 8 | 48 | 0 |
| F | 0 | 0 | 0 | 1 | 0 | 1 |

Most disagreements fall in two places. One is the C/D boundary: whether two crops show "the same design" or only "the same generic trace pattern". The other is A/B: whether a shifted crop counts as a duplicate or as the same scene. Pass B noticed horizontally mirrored copies more often than Pass A did (5 B→A, 2 D→A).

## Control performance

| control set | n | Pass A called A/B | Pass B called A/B | called A/B/C (A / B) |
|---|---|---|---|---|
| synthetic transformed duplicates (should be A/B) | 18 | 14 (78%) | 17 (94%) | 15 / 17 |
| random cross-source pairs (should be D/E) | 12 | 0 | 0 | 0 / 0 |
| random within-source pairs (should be D/E) | 12 | 0 | 0 | 1 / 1 |

Visual adjudication separates the controls well. False positives (A/B on a negative): 0 of 24 in both passes. Sensitivity to synthetic duplicates: 78% in Pass A and 94% in Pass B. The misses were heavily cropped plus JPEG-degraded copies of near-featureless DsPCBSD+ crops. Within-source random pairs from PCB-Defect were called C (same board family) once in each pass. That is correct: PCB-Defect is one family of DIY boards. **So the review is informative, but it under-detects duplicates of low-texture crops by roughly 5–20%.**

## Final AI-adjudicated labels (300 candidates)

| label | A | B | C | D | E | F |
|---|---|---|---|---|---|---|
| count | 21 | 32 | 47 | 162 | 32 | 6 |

Basis: 266 agreed and 34 adjudicated. Per-pair labels, confidence and rationale are in `VISUAL_REVIEW_300.csv`.

## What the images show

1. **DsPCBSD+ contains mirrored copies.** Many A labels are horizontally flipped copies, some also brightness-changed, of the same crop, and they sit in both of the source's train2017 and val2017 folders. This is ordinary near-duplicate leakage inside the source dataset's own split.
2. **PCB-IND pairs labelled B** are usually shifted crops of the same scene. The same scratch, trace bend or bridge defect appears at a displaced position.
3. **PCB-Defect pairs** are mostly C: crops of the same family of DIY boards with the same trace texture, but different regions and different defects.
4. **Cross-source pairs are not related.** 0 of 66 were called A/B and 1 of 66 was called C. Every cross-source link the M3 graph makes is, on this evidence, a false positive.
5. **pHash-only REVIEW_REQUIRED pairs are mostly false positives.** DsPCBSD+ was 0 of 18 A/B and cross-source 0 of 18; PCB-IND was 9 of 25.

## Limitations of this review

- One AI model labelled both passes and adjudicated, and it may have remembered pairs between passes. κ therefore overstates inter-rater reliability.
- A judgement such as "same design family" in 300×300 px crops is often underdetermined. 6 pairs stayed F.
- The 300 pairs are a stratified sample with about 9 per stratum, not a random sample of the graph. The rates per stratum below cannot be pooled into one precision for the whole graph without weights (see `GROUP_VALIDITY.md`).
- Nothing here is a statement about physical provenance. A/B mean *visual* evidence of a shared capture, never verified identity of the board.
