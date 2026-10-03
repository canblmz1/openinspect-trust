# Source-shift red-team

## Reproduction

All B numbers reproduce exactly with the independent Ultralytics re-run (`STATISTICAL_RED_TEAM.md` §0): DsPCBSD+ held out 16.37 (B-natural 15.21), PCB-IND 19.17 (19.72), PCB-Defect 0.33. In-distribution references: A1 items of DsPCBSD+ 43.74, PCB-IND 56.82, A0's PCB-Defect items 47.62.

## Is PCB-Defect ≈ 0.3 an evaluation bug? No.

| check | result |
|---|---|
| Same 93 PCB-Defect test items, A0 model vs B-strict-pcb-defect model | **47.62 vs 0.27** mAP50-95 |
| A0 on those items: GT boxes found at IoU ≥ 0.5 (conf ≥ 0.25) | 84 / 94, **all 84 with the correct class** (22/23/20/19 across the four classes, zero confusions) |
| → coordinates, class IDs, crop offsets, label conversion | correct (an in-distribution model scores them normally) |
| B-strict-pcb-defect on all 939 items: GT found at IoU ≥ 0.5 | 93 / 971, of which 76 with the correct class (76 of the 77 spurious_copper hits) |
| Its confident predictions (conf ≥ 0.25) by class | short 2, open 1, mouse_bite 2, **spurious_copper 2,373** |
| Confident predictions not matching any GT box | 2,226 (2.4 per image); median top confidence per image 0.70 |
| Per-class AP50-95 | short 0.0, open 0.0, mouse_bite 0.08, spurious_copper 1.24 |
| Taxonomy coverage | all four classes present in training (DsPCBSD+ and PCB-IND) and in the PCB-Defect test (222 / 241 / 304 / 204 boxes) |

Inspection of rendered predictions (`figures/pcbdefect_preds.jpg`, GT green, predictions red): the held-out model draws confident "spurious_copper" boxes around **ordinary copper traces and pads** of the PCB-Defect boards (yellow-green substrate, wide etched copper). It mostly ignores the actual open, short and mouse-bite defects. Training data come from factory AOI crops (DsPCBSD+ 226 px JPG; PCB-IND 300 px JPG, dark solder mask). There, "isolated copper on a non-copper background" is almost always spurious copper. On a lab-flatbed-scanned DIY board, every trace looks like that.

**The 0.3 is real.** It is a semantic transfer failure caused by an appearance prior tied to the acquisition domain. The defects are not invisible, and nothing is mis-scored.

## Source identity is trivially encoded

Source probe reproduced: random forest, GroupKFold by constraint group, balanced accuracy.

| features | balanced accuracy |
|---|---|
| width + height + aspect + format | **1.00** |
| + box count | 1.00 |
| file bytes alone | 0.68 |
| box count alone | 0.31 (chance 0.33) |

Signatures: DsPCBSD+ = 226×226 (or 108×108) JPG; PCB-IND = 300×300 JPG; PCB-Defect = PNG crops, mostly 300×300 plus a range of sizes, from a flatbed scan.

## Interpretation

- Source-held-out collapse is **mostly a source/domain identity effect**: acquisition device, substrate, colour, resolution and crop generation. The datasets encode severe domain differences, and a size/format probe identifies the source perfectly.
- That does not make B uninformative. It is a realistic estimate of what happens when a detector meets a new line or imaging setup. But the honest phrasing is "a model trained on two AOI sources does not transfer to a third acquisition domain". The phrasing "cannot generalise to unseen defect semantics" is not supported: the defect *labels* are shared, and the failure is visual-domain-driven.
- PCB-Defect is an extreme case: lab scans of hobby boards versus industrial AOI. DsPCBSD+ and PCB-IND held out (16–19 vs 44–57) are the more representative measures of cross-source shift, and still very large.
- B-natural − B-strict (DsPCBSD+ −1.15, PCB-IND +0.55): keeping machine-linked cross-source items did not help. That agrees with the visual finding that cross-source links are false (0/66 related).
- Practical magnitude: source shift costs 27–47 pp. The exposure effect is about 2 pp overall and about 4–7 pp on exposed items. **For deployment, source shift is the more important result by an order of magnitude.**
