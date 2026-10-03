# Terminology decision (follows the images, not the hypothesis)

Evidence base: 60 probe→mate pairs from D0, AI-adjudicated (`AI_PM_VISUAL_FINDINGS.md`). 0 duplicates; 4 same-instance-like (7%); 9 same design (15%); 28 structurally similar (47%); 16 not related (27%); 3 ambiguous.

| term | verdict | reason |
|---|---|---|
| "near-duplicate leakage" | **MISLEADING** | 0/60 pairs are near-duplicates, including 0/20 in the DINO "near" band. The term describes a mechanism the images do not show. |
| "duplicate leakage" | **MISLEADING** | Same as above, and stronger. |
| "same-board leakage" | **TOO STRONG** | Only 4/60 pairs (2/20 in the board-ID subset) show visible evidence of a shared specimen. Board ID is provenance metadata. It is not visual evidence, and in 14/20 such pairs the nearest mate is visually unrelated. |
| "same-family exposure" | **ACCEPTABLE WITH QUALIFICATION** | Fits the largest visual class (C/D 62%), but 27% of nearest mates are not visibly related. Say "mostly same-family". |
| "visual-similarity exposure" | **ACCEPTABLE WITH QUALIFICATION** | Accurate about how groups were built (DINO similarity + metadata) and consistent with the Δ dose-response. Qualify with "machine-measured", because the metadata-linked probes are not visually similar. |
| "group exposure" | **SUPPORTED** | Describes exactly what the design manipulated: C0 trains on members of the probe's constraint group (similarity component, crop parent or metadata group) and C1 does not. It makes no claim about the visual relationship. |
| "related-example exposure" | **ACCEPTABLE WITH QUALIFICATION** | Reasonable plain-language summary, provided "related" is defined (shared machine-detected group: same component, crop parent or source metadata) and the review is cited as showing mostly family-level relations. |

## Is "leakage" acceptable?

Yes, **as "train–test group leakage"**, in the established sense of patient- or subject-level leakage: test items share a group with training items, and that inflates scores on those items. It must never be modified by "near-duplicate", "duplicate" or "confirmed".

## Replacement phrase

> **"train–test group exposure (machine-detected, mostly same-family visual-similarity groups)"**

Short form for titles: **"group leakage"** or **"related-example exposure"**. For the graded result: **"optimism grows with the visual similarity of the nearest exposed training image."**
