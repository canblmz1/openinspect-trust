# What OpenInspect-Trust M7 may claim

> **Superseded on 2026-10-03 by `reports/m7_final/FINAL_SAFE_CLAIMS.md`**, written after the five replication runs (D1 seeds 1–2, D2 seed 1) and the probe–mate AI review. Changes: D1 controls returned to ~0 (mean +0.22 over 3 seeds); pooled probe effect +3.7 (+1.7 to +5.7); the dose-response is concentrated in the top exposure bin (+6.9, 8/8 seeds), but the continuous correlation is weak; the main term is now "train–test group exposure"; and "near-duplicate", "same-board" and "higher similarity causes higher gain" are DO NOT CLAIM. The text below is kept as the pre-replication record.

## SAFE CLAIMS (directly supported)

1. On one byte-identical test set (D0, 407 images), YOLO11n trained with the machine-detected group-mates of 194 test images (C0) scored higher than YOLO11n trained with profile-matched replacements (C1) in 3 of 3 seeds: +1.76 mAP50-95 points on average. The numbers are exactly reproducible from the released checkpoints.
2. The gain is concentrated on the exposed test images. Probes +3.91 pp (positive in all 12 C0×C1 model pairings); unexposed controls −0.17 pp in D0 and +0.02 pp in D2.
3. The gain grows with how close the exposing training item is in feature space. Probes with the strongest exposure gained +6.8 (D0, 3 seeds), +7.4 (D1) and +6.7 pp (D2), and the gradient also holds under DINOv2-base embeddings.
4. The probe/control split is not an arbitrary partition. Against 2,000 source-stratified cluster placebos, D0 and D2 lie at p ≈ 0.01 (one-sided).
5. Holding out a whole source collapses performance far more than group exposure inflates it: 16–19 vs 44–57 mAP50-95 for DsPCBSD+ / PCB-IND, and 0.3 vs 47.6 for PCB-Defect, where the held-out model mistakes ordinary copper traces on the scanned boards for spurious copper.
6. The three sources are perfectly identifiable from image size and format alone. Held-out-source results therefore measure acquisition/domain shift.
7. Of the 300 M3 review pairs, AI visual adjudication judged 18% duplicate-like and 33% at least same-family. Cross-source machine links were visually unrelated in 65 of 66 pairs. **AI visual adjudication was performed on 300/300 review pairs. This is not a substitute for independent human validation.**
8. DsPCBSD+ contains horizontally mirrored copies of crops (visually adjudicated), some across its own train2017/val2017 folders.

## CAUTION CLAIMS (only with the stated qualification)

1. "Group exposure makes this benchmark optimistic": qualify as *modestly* (about 2 pp overall). Once training-seed variation is included, the overall interval touches zero (−0.01 to +4.05).
2. "Probe − control +4.08 pp": report the hierarchical interval (−0.68 to +8.46, P(≤0) ≈ 0.05) beside the test-sampling-only interval, and say D1 did not replicate it (+0.84).
3. "Replicated in D2": one seed each; D1 controls moved +3.09 for unresolved reasons.
4. "Similarity groups": say *machine-detected visual-similarity groups*, mostly same-family or same-scene. Group membership depends on the embedding: about 43% of probes are not exposed under DINOv2-base groups.
5. "Same board / same batch": for PCB-IND, the metadata group (board ID and side) is provenance from the source dataset. Say "same board ID in the source metadata", not that physical identity was verified.
6. "Larger than training noise": only for the 3-seed means and for the strongly exposed probes. Single-seed overall effects sit within subset-level training noise.
7. "Domain shift": acceptable, but say acquisition/source shift. The source signature is trivial, so B cannot separate defect-semantics generalisation from imaging differences.

## DO NOT CLAIM

1. **"Near-duplicate leakage" as the mechanism of the M7 effect.** Only 8% of probe–mate pairs look duplicate-like, and the largest gain comes from PCB-IND metadata-group probes whose nearest mates look like different regions.
2. Any statement that two images show one and the same physical circuit board.
3. "Human-validated" or "human review complete". No person reviewed the pairs.
4. "Confirmed" duplicates or leakage of any kind.
5. "Causal effect of near-duplicates." At most: "the C0/C1 swap of group-mates caused the gain on exposed items, under one architecture and limited seeds."
6. "The model cannot generalise to unseen defect semantics." The labels are shared across sources, and the failure is visual-domain-driven.
7. "Deployment performance" inferred from any of these numbers. Test sets are public-dataset crops, not a production line.
8. That the result holds for other detectors, other domains or larger models.
9. That B-natural vs B-strict shows cross-source leakage. The links were visually spurious and the difference is within noise.

## Word-by-word decision

| word | verdict |
|---|---|
| leakage | **allowed with qualifier**: "group-exposure leakage" or "train–test group leakage"; never "confirmed leakage" |
| near-duplicate | **only** for the visually adjudicated A pairs (e.g. DsPCBSD+ mirrored copies); not for M7 probes |
| same-board | **no** as a visual claim; "same board ID in source metadata" for PCB-IND provenance only |
| same-family | **yes, with "visually adjudicated (AI)"**: the most accurate description of most probe–mate links |
| visual similarity | **yes**: "machine-detected visual-similarity group" |
| benchmark optimism | **yes, "modest"**: about 2 pp overall, about 4–7 pp on exposed items |
| causal effect | **narrowly**: "the controlled swap increased mAP on exposed items"; not "near-duplicates cause" |
| domain shift | **yes**: acquisition/source shift, with the source-identity caveat |
| deployment performance | **no** |
