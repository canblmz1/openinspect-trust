# Table S5. Source-held-out evaluation (mAP50-95; one seed per model)

| held-out source | held-out test images | in-distribution reference (other same-source test images) | B-strict (source held out) | B-natural (machine-linked items kept) | difference (strict − reference) |
|---|---|---|---|---|---|
| DsPCBSD+ | 1,768 | 43.74 (A1) | 16.37 | 15.21 | −27.37 |
| PCB-IND | 1,713 | 56.82 (A1) | 19.17 | 19.72 | −37.65 |
| PCB-Defect | 939 | 47.62 (A0) | 0.33 | — (identical to strict) | −47.29 |

Same 93 PCB-Defect images: A0 47.62 vs held-out model 0.27. Source identity predicted from width, height and format: 100% balanced accuracy.
