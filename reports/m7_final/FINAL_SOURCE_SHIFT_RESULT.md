# Final result: source / acquisition shift (unchanged; no retraining)

The values below are reproduced exactly by two independent evaluations: the M7 evaluator and a plain Ultralytics `val` re-run.

| held-out source | test items | in-distribution reference | source held out (B-strict) | B-natural | drop |
|---|---|---|---|---|---|
| DsPCBSD+ | 1,768 | 43.74 (A1's DsPCBSD+ test items) | 16.37 | 15.21 | −27.4 |
| PCB-IND | 1,713 | 56.82 (A1's PCB-IND test items) | 19.17 | 19.72 | −37.7 |
| PCB-Defect | 939 | 47.62 (A0's PCB-Defect test items) | **0.33** | = strict | −47.3 |

The in-distribution references use other test items of the same source, so each difference compares two different item sets. For PCB-Defect, the same 93 items score 47.62 under A0 and 0.27 under the held-out model.

## Why PCB-Defect collapses (verified, not an evaluation bug)

- A0 finds 84 of 94 ground-truth boxes on those items, all with the correct class. Coordinates, class IDs and crop offsets are therefore correct.
- The held-out model fires confidently (median top confidence 0.70) but calls almost everything spurious copper (2,373 of 2,378 confident boxes). It boxes ordinary copper traces and pads of the laboratory-fabricated boards, and it finds only 93 of 971 defects.
- Training sources are dark-mask AOI crops (DsPCBSD+ 226 px JPG, PCB-IND 300 px JPG). PCB-Defect is crops of high-resolution images of laboratory-fabricated single-layer FR4 boards (Rashid et al., Data in Brief 2025), released here as PNG. "Copper on a non-copper background" means a defect in the first case and normal circuitry in the second.

## Source identity is trivial

Image width, height and format identify the source with 100% balanced accuracy (random forest, group-aware CV).

## Interpretation

These results measure **acquisition / source-domain shift**: imaging device, substrate, resolution, crop generation. They do not show that the detector cannot generalise to unseen defect types; the four defect classes are shared across sources. B-natural (which keeps machine-linked cross-source items in training) does not help, which agrees with the visual finding that cross-source links are not meaningful.

**Practical ranking:** source shift costs 27–47 points. Group exposure inflates scores by about 2 points overall and about 4 points on exposed items. For anyone deploying a PCB detector, a new line, scanner or board family is the larger risk by an order of magnitude.
