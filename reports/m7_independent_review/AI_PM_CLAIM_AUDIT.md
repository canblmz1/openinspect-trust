# Claim audit and final verdict of the probe–mate review

## Claims

**1. "Near-duplicate leakage increases PCB detection performance." NOT SUPPORTED.**
Visual adjudication found no near-duplicate among the 60 probe→mate pairs. Only 4 (7%) show a shared specimen or capture series, and even pairs in the DINO "near" band were same-family or structurally similar, never duplicates. M7 measured a gain from training on group-mates. Those group-mates are not near-duplicates, so the claim attributes the gain to a relationship that is essentially absent from the data. (Separately, the 300-pair review did find true mirrored duplicates inside DsPCBSD+, but they are not what the M7 probes are exposed to.)

**2. "Exposure to related PCB group members increases performance on related test images." SUPPORTED (with qualification).**
The controlled swap of group-mates raised D0 probe mAP by +3.9 pp, with controls near zero in D0 and D2. The exposed images are mostly *related* (C/D 62%, B 7%). The qualifications: the overall effect is modest; the seed-aware interval for probe − control is borderline; D1 controls also moved; and about 27% of shown mates are not visibly related. "Related" must be defined as "member of the same machine-detected group".

**3. "Performance gain increases with train–test visual similarity." PARTIALLY SUPPORTED.**
Strong support from the earlier exposure-Δ analysis on all 194 D0 probes: +6.8 pp at Δ > 0.08 in all three seeds, the same pattern in D1 and D2, and under DINOv2-base. This review adds that Δ tracks *visual* relatedness (ρ = 0.52; no unrelated pair at Δ > 0.08) and that gain is ordered by visual category (B > C > D > E in per-image recall). The visual-category-to-gain link in the 60-pair sample is not significant (ρ = 0.19, p = 0.16), so the claim rests mainly on embedding similarity, with the visual review as corroboration.

**4. "Same-board exposure creates the largest observed gain." NOT SUPPORTED.**
The +11.3 pp figure belongs to PCB-IND probes linked by *board-ID metadata*. Visually, 14/20 of those probe→mate pairs are unrelated and only 2/20 overlap. Within the sample, the per-image gain sits in the 2 overlapping pairs (+0.45), while the 16 unrelated ones show none (−0.02) and swing from +13 to −12 pp across seeds. The subset's high mean is better explained by a few genuine overlaps plus small-sample seed noise than by "same-board exposure" as such. The 2-vs-16 comparison is too small to establish the opposite either.

**5. "Cross-source machine similarity links are meaningful." NOT SUPPORTED.**
The 300-pair review found 0/66 cross-source pairs duplicate-like and 1/66 same-family. In this review, the 7 cross-source control→neighbour pairs were labelled D or E. Cross-source links in the graph are artefacts of generic texture similarity and transitive chaining.

## Final scientific verdict (Phase 13)

1. **True near-duplicates:** 0 of 60 probe pairs (0 of 90 reviewed).
2. **Same physical board or capture series (visually likely):** 4 of 60 (7%); 0 of 30 controls.
3. **Same design or family (C):** 9 of 60 (15%); 4 of 30 controls.
4. **Structurally similar only (D):** 28 of 60 (47%); 14 of 30 controls.
5. **Unrelated (E/F):** 16 of 60 (27%); 12 of 30 controls.
6. **Ambiguous (G):** 3 of 60 (5%).
7. **Does visual relationship strength increase with DINO similarity?** Yes (ρ 0.49 for probes, 0.59 overall). The top band reaches same-family, not duplication.
8. **Does it increase with the observed M7 gain?** Directionally yes (B > C > D > E per-image), but not significantly in 60 pairs.
9. **Are the high-similarity +6–7 pp gains visually credible?** Yes, as exposure to closely related images (none unrelated, 35% same-design or same-instance). No, as duplicate memorisation.
10. **Does PCB-IND same-board-ID exposure look physically meaningful?** Mostly no: 2/20 overlapping crops, 14/20 visually unrelated. The board ID is provenance that the images rarely corroborate.
11. **Should M7 use the word "leakage"?** Only as "train–test group leakage" (patient-level-leakage sense), never as near-duplicate, duplicate or confirmed leakage.
12. **Replacement for "near-duplicate leakage":** *"train–test group exposure (machine-detected, mostly same-family visual-similarity groups)"*; short form *"group leakage"*.
13. **Does this review strengthen or weaken the paper?** It **weakens the original framing** (near-duplicate; same-board as the largest effect) and **strengthens the defensible framing**. The graded result now has visual corroboration: closer exposed images are visibly more related and go with larger gains, and the "no visible relation, no gain" pattern argues against a pure artefact. The net effect is a narrower but more honest paper.
14. **Is the workshop/preprint recommendation (C) still justified?** **Yes, unchanged.** The review reinforces two of its conditions. First, the paper must reframe around graded group exposure. Second, real human validation is still needed: the two AI passes agree only at κ = 0.17 on the fine categories, and same-model agreement is not inter-rater reliability. The 90 prepared pairs and the A–G protocol are ready for two human raters.

---

AI visual adjudication was performed on the prepared probe–mate pairs.
This review is not a substitute for independent human validation.
If both review passes were produced by the same underlying model,
agreement statistics measure internal consistency rather than independent
inter-rater reliability.
