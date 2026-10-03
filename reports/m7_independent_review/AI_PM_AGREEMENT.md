# Probe–mate review: agreement between the two AI passes

AI visual adjudication was completed. Two blinded AI review passes were performed. **Both used the same underlying model (Claude Opus) in separate, fresh agent contexts, so agreement is an internal consistency measure, not independent inter-rater reliability.**

## Setup

- Input: `data/pm_items.json`, 90 pairs. All 180 image files are present and readable in `C:\data\openinspect\release\v0.1\images`; none are missing.
  - 60 **probe → nearest exposing mate** pairs (D0): 12 crop sibling, 16 similar pair, 12 same component, 20 same metadata group. The mate shown is the C0-only training image closest to the probe in DINOv2-small space. It is not necessarily the only or the most visually related mate.
  - 30 **control → nearest C0-train image** pairs (comparison set; not probe–mate pairs).
  - Sources: 34 DsPCBSD+ pairs, 23 PCB-Defect, 26 PCB-IND; 7 control pairs cross sources.
- Blinding: each reviewer saw only a random 3-digit code and two images. Each reviewer had its own shuffle and its own codes (15 contact sheets of 6 pairs). Reviewers had no metadata, no scores, no link type, no gain, no earlier labels and no access to the other reviewer.
- Reviewer A and Reviewer B: two fresh subagents with clean context and identical instructions and category definitions (A–G). Their only permitted input was their own sheet folder.

## Results

| set | n | exact agreement | Cohen κ (7 categories) | 95% CI (bootstrap) | linear-weighted κ (A–F, excl. G) | broad κ (instance / family / structural / none / ambiguous) |
|---|---|---|---|---|---|---|
| all | 90 | 40% | **0.17** | 0.03–0.30 | 0.31 | 0.18 |
| probe pairs | 60 | 40% | 0.20 | 0.05–0.35 | 0.33 | 0.23 |
| control pairs | 30 | 40% | 0.06 | −0.22–0.29 | 0.22 | 0.06 |

Scientific groupings (all 90; counts: Reviewer A / Reviewer B):

| grouping | A count | B count | agreement | κ |
|---|---|---|---|---|
| duplicate-like (A) | 1 | 0 | 99% | 0.00 |
| same-instance-like (A+B) | 2 | 2 | 98% | 0.49 |
| same-family-like (A+B+C) | 13 | 30 | 79% | 0.45 |
| meaningfully related (A–D) | 35 | 63 | 58% | 0.22 |
| not meaningfully related (E+F) | 50 | 24 | 58% | 0.20 |
| ambiguous (G) | 5 | 3 | 98% | 0.74 |

Confusion matrix (rows: Reviewer A, columns: Reviewer B):

| A\B | A | B | C | D | E | F | G |
|---|---|---|---|---|---|---|---|
| A | 0 | 1 | 0 | 0 | 0 | 0 | 0 |
| B | 0 | 0 | 1 | 0 | 0 | 0 | 0 |
| C | 0 | 0 | 10 | 1 | 0 | 0 | 0 |
| D | 0 | 0 | 12 | 5 | 5 | 0 | 0 |
| E | 0 | 0 | 5 | 27 | 18 | 0 | 0 |
| F | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| G | 0 | 1 | 0 | 0 | 1 | 0 | 3 |

## Reading

- **The two passes agree on the important negative:** neither found more than one or two duplicate-like or same-specimen pairs among 90.
- **They disagree on how much "relatedness" to grant.** Reviewer A is conservative: it calls "same board style, different region" E. Reviewer B grants D to the same pairs. Most disagreements (27 E→D and 12 D→C) are one ordinal step apart, which is why the linear-weighted κ (0.31) is higher than the nominal κ (0.17).
- The largest systematic split concerns the 12 PCB-Defect crop siblings (green hand-etched boards, different regions): A gave E to all 12 and B gave D to all 12. Visually this is a convention question, "same board style" versus "generic", not a perceptual one.
- With κ ≈ 0.2 the fine C/D/E boundaries are **not reliable** from these images. Conclusions in this review therefore rely on the coarse groupings with κ 0.45–0.74 (same-instance, same-family, ambiguous) and on the adjudicated labels. The fine boundaries are not used as evidence.
- 54 of 90 pairs disagreed. Every one was adjudicated with both labels visible (`AI_PM_ADJUDICATED.csv`), and G was used where evidence stayed insufficient.

Agreement is an internal consistency measure, not independent inter-rater reliability.
