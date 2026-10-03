# Final Reviewer #2 audit of the finished manuscript (3 October 2026)

**Stance.** Try to reject the paper. Every objection below was checked against the manuscript and the frozen CSVs. Where it held, the manuscript was fixed; the "action" column says what changed.

| # | objection | found in the manuscript? | severity | action / status |
|---|---|---|---|---|
| 1 | **Novelty overclaim**: leakage is known. | No. Section 1 and Section 2 state that leakage, near-duplicates, group-aware splitting and domain shift are known, and claim only a controlled case study. "First" appears nowhere. The prior-art table (S7) shows the closest designs. | was MAJOR in the draft | resolved; positioning sentence: "we did not identify prior work combining these elements" |
| 2 | **Causal overclaim.** | Placebo p-values are explicitly "not that exposure caused the difference". The discussion says "associated with". The design is a randomised controlled swap, so the narrow causal reading is defensible and stated only for this setup. | MODERATE | resolved (claim register #12) |
| 3 | **Hidden negative results.** | D1 seed 0 control +3.09, D2 seed 1 probe = control, two near-zero probe − control pairs, the weak continuous trend and the non-replication of the metadata-only gain are all in the main text (Tables 1 and 5, Figure 3, Section 8). | was MAJOR | resolved |
| 4 | **Improper CI interpretation.** | Test-sampling, seed-only and combined intervals are reported separately. The text says the combined interval for D0 probe − control includes zero, and that 2–3-seed t-intervals are very wide. The pooled interval relies on inverse-variance weighting of bootstrap-derived variances (an approximation; stated). | MODERATE | resolved; residual: pooling assumes exchangeable designs, now stated in methods |
| 5 | **D1/D2 cherry-picking.** | All 8 seed pairs are shown, including the D1 C0 replicate sensitivity (+4.60). D2 is explicitly "not counted as a successful replication". The D1 seed-1 C0 replicate was chosen by a rule fixed before the new results (first-created). | was MAJOR | resolved |
| 6 | **Post-hoc exposure strata.** | Disclosed. The strata were defined after five of eight seed pairs had been evaluated, and only the three later pairs are out-of-sample. The abstract says "including three trained after the stratum was defined". | MAJOR → MODERATE | resolved by disclosure; still a limitation |
| 7 | **Pre-registration claim.** | Checked. The primary estimand ("mAP50-95(C0) − mAP50-95(C1) on the probes of design 0, mean over the three training seeds") is in the M7 analysis plan, committed before any training (2026-10-01). The pre-planned probe-link split was **missing** from the draft. | was MAJOR | fixed: pre-planned link-type split added (Table 5). Visually linked probes positive in 8/8 seed pairs; metadata-only gain did not replicate. |
| 8 | **AI review misrepresented as human.** | No. "Independent human validation was not performed" appears in the abstract, Section 6.2 (bold), Table 4's caption, the limitations and the conclusion. Same-model agreement is described as internal consistency. | — | compliant |
| 9 | **Source shift overinterpreted.** | No. It is called acquisition/source shift, the trivial source probe is stated next to the result, and "not inability to learn the defect classes" is explicit. | — | compliant; residual: one seed per source model, now stated in Table 6's caption |
| 10 | **Unsupported EVREN claims.** | The manuscript mentions the platform only as the training environment and its non-determinism. The anonymised version removes the name. Suggested platform capabilities appear only in the separate brief, as "suggested by this case study". | — | compliant |
| 11 | **Stale or unverifiable citations.** | All 15 references verified against primary records (`CITATION_AUDIT.md`). Robust AD venue corrected to CVPR Workshops. Figueiredo & Mendes added. Unverified automotive survey items not cited. SciSpace/Scite unavailable, which is disclosed. | was MODERATE | resolved; open: full PCB-IND author list |
| 12 | **Numbers inconsistent with CSVs.** | The automated audit (`scripts/audit_numbers.py`) found one manuscript mismatch (+7.74 → +7.73) and four in a final report; all fixed. Final run: all match. | was MINOR | resolved |
| 13 | **Probe/control is confounded with grouped/singleton.** | Stated in the design section and the limitations. The paper does not claim the confound is removed. | MODERATE | disclosed; not fixable without new experiments |
| 14 | **Single architecture, single domain, small seeds.** | Stated in the limitations and the discussion; no generalisation claim is made. | MAJOR for a full conference, acceptable for a workshop | disclosed |
| 15 | **Effect size relative to training noise.** | Run-to-run differences (1.13 overall, 2.22 on controls) are reported next to the effect, and the discussion uses them to argue for replicated runs. | MODERATE | disclosed |
| 16 | **Is the C0/C1 swap balanced?** | C0 has 4–6% more training boxes, mainly short and open; stated in the design section. | MINOR | disclosed |
| 17 | **Reproducibility.** | Configuration, manifests, hashes and analysis scripts are released. Weights are withheld, with reasons. The re-run from the sanitised scripts reproduced every statistic. | — | compliant |
| 18 | **Unconverted / uncompiled LaTeX.** | The `.tex` is generated and passes static checks but was not compiled (no TeX toolchain). | MINOR | author action: compile and proofread before submission |

## Residual weaknesses a real reviewer may still raise

1. No independent human validation (the largest remaining limitation; disclosed).
2. Only 2–3 seeds per design and one architecture.
3. The strongest-stratum result is partly post hoc.
4. Probe/control structural confound.

None is hidden. None is fatal for a workshop or preprint. Items 2 and 1 would likely be decisive at a full conference.

## Verdict after this pass

**B — WORKSHOP / PREPRINT READY.** Not A: one architecture and domain, few seeds, no human validation. The manuscript's claims now match `reports/m7_final/FINAL_SAFE_CLAIMS.md`.
