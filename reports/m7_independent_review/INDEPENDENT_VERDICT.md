# OpenInspect-Trust M7: independent review verdict

> **Pre-replication record, superseded 2026-10-03.** The final numbers are in `reports/m7_final/` (5 replication runs added; the analysis was re-run with 2,000 bootstrap draws and 10,000 placebo relabellings, so intervals differ from those below). Do not cite numbers from this file; see `reports/m7_final/FINAL_SCIENTIFIC_VERDICT.md`.

Reviewer: Claude (AI), acting as an independent skeptical reviewer, 2–3 October 2026. Read-only with respect to EVREN: no EVREN API call was made in this review. Nothing was trained, nothing was committed, and history was not touched. Cancelled, duplicate and replicate runs were used as evidence, not removed.

**AI visual adjudication was performed on 300/300 review pairs. This is not a substitute for independent human validation.**

Supporting files: `STATISTICAL_RED_TEAM.md`, `PLACEBO_TESTS.md`, `PROBE_CONTROL_CONFOUND_AUDIT.md`, `D1_INVESTIGATION.md`, `REPRESENTATION_SENSITIVITY.md`, `GROUP_VALIDITY.md`, `VISUAL_REVIEW_SUMMARY.md`, `VISUAL_REVIEW_300.csv`, `POSITIVE_NEGATIVE_CONTROLS.csv`, `SOURCE_SHIFT_RED_TEAM.md`, `PRIOR_ART_TABLE.md`, `NOVELTY_AUDIT.md`, `REVIEWER_2_REPORT.md`, `SAFE_CLAIMS.md`; raw outputs in `data/`, code in `scripts/`, plots in `figures/`.

## 1. What was verified

| item | result |
|---|---|
| Re-evaluation of all 20 checkpoints with plain Ultralytics 8.3.0 `val` (independent script) + an independent AP implementation | **Exact match** to `reports/m7` (max diff < 0.0001 pp; tolerance 0.01 pp) |
| C0/C1 test and val sets identical (IDs, SHA-256 of image and label files, release hashes) | **Yes**, D0/D1/D2 |
| Training sets differ only by mates ↔ replacements; common files byte-identical | **Yes** |
| Probes exposed in C0 and not in C1; controls exposed in neither | **Yes** (constraint groups); feature-space Δ ≈ 0 for controls |
| Replacement profile | Matched source and format; C0 has 4–6% more boxes (short/open surplus) |
| D0 point estimates (+1.76 / +3.91 / −0.17 / +4.08) | **Reproduced exactly** |
| Bootstrap method | Re-implemented; agrees. **Omits seed variance** (material) |
| PCB-Defect 0.33 | **Real, not a bug**: in-distribution A0 scores the same items 47.6 with every located box correctly classed |
| Source identity from size + format | **100% balanced accuracy** (reproduced) |
| 300-pair visual review | Done: 2 blinded passes + adjudication, κ = 0.82, controls separated (0/24 false positives) |

## 2. What the hostile audit found

1. **The effect is real but smaller and less certain than the M7 headline implies.** With seed resampling, the overall D0 interval is −0.01 to +4.05 pp and probe − control is −0.68 to +8.46 (P(≤0) ≈ 0.05). The probe gain itself stays robust: +0.67 to +7.45, and positive in every one of the 12 C0×C1 model pairings.
2. **The strongest evidence is a dose-response M7 did not report.** Probes whose exposing training items are closest in feature space gain +6.6 to +7.4 pp in D0 (6.21 / 7.91 / 6.28), D1 and D2. Weakly exposed probes gain about +1.4 pp. The gradient survives a change of embedding (DINOv2-base) and appears even in D1.
3. **The groups are not near-duplicate groups.** Visually, 8% of probe–mate pairs and 18% of all review pairs are duplicate-like; most are same-family. The largest single gain (+11.3 pp, PCB-IND "same metadata group" probes) comes with nearest mates that look like *different regions* of boards sharing a source-metadata board ID. "Near-duplicate leakage" is the wrong name for what M7 measured. "Exposure to same-family / same-board-ID group-mates" is the right one.
4. **D1 remains unexplained.** Bug, exposure and composition are ruled out. Training noise is plausible (identical replicates differ by 2.2 pp on controls) but unproven.
5. **Probe vs control = grouped vs singleton** (AUC 0.98). This is a structural confound the design cannot fully remove. Partial rebuttals hold in D0: grouped controls did not gain, and within-probe dose-response exists.
6. **The machine-similarity graph has real errors.** Cross-source links are false (0/66 related), PCB-Defect family links are 6% related, and pHash-only links in DsPCBSD+ are 0% related. Mirrored copies, the clearest true duplicates, are mostly *missed* by both embeddings.
7. **Source shift dominates.** It costs 27–47 pp against about 2 pp for group exposure. It is driven by acquisition domain: the PCB-Defect model labels normal copper on DIY scans as spurious copper.

# Independent Reviewer Opinion

**What happened in this experiment?** Swapping a few hundred training crops for profile-matched alternatives changed YOLO11n's accuracy on the specific test crops whose same-family or same-board-ID siblings were in the swapped set. The model learned appearance specifics of those boards and capture sessions (colour, trace geometry, defect style), and that helped on their siblings. It is not mostly memorising duplicates. On top of this, individual training runs differ by 1–2 pp on subsets, which is the same order as the overall effect.

**Do I believe D0 reflects a real exposure effect?** Yes. The exact reproducibility, 12/12 positive probe pairings, the placebo tail (p ≈ 0.01 in D0 and D2) and above all the replicated dose-response convince me that exposure to visually close group-mates raises scores on those test items.

**How much confidence?** About 85% that a real, positive exposure effect on strongly exposed items exists in this setup. About 60% that the specific "probes move, controls do not" pattern would replicate with more D1-style designs. Low confidence that +1.76 pp overall is a stable number: it could be 0.5–3 pp.

**Most convincing result:** the dose-response (+6.8 pp for strongly exposed probes in all three seeds; same direction in D1, D2 and under DINOv2-base).

**What worries me most:** that the paper's vocabulary ("near-duplicate", "leakage groups") overstates what the images show. Second, that probe/control is confounded with grouped/singleton, and D1 shows that controls can move by 3 pp.

**Is +1.76 overall practically meaningful?** Barely. It is within the range of seed-to-seed variation people already ignore when comparing YOLO variants on PCB benchmarks. The honest practical message is "group exposure inflates this benchmark only modestly".

**Is +3.91 on probes scientifically meaningful?** Yes, as a controlled demonstration that train–test group exposure measurably helps the exposed items. It is small in absolute terms, but clean in design.

**Does control ≈ 0 strengthen the interpretation?** In D0 and D2, materially yes: it is what separates "exposure" from "C0 is just a better training set". D1 shows it is not guaranteed.

**Does D1 substantially weaken it?** It weakens the *clean binary* story substantially. It does not weaken the *graded* story much, because D1's strongly exposed probes still stand out.

**Does D2 restore confidence?** Partly. It is one seed, but its pattern (probes +4.6, controls +0.0, placebo p = 0.008) is the D0 pattern.

**Is source shift the more practically important result?** Yes, clearly, and by an order of magnitude. A PCB inspection team should worry about a new line or scanner far more than about duplicate crops in a public benchmark.

**Is the PCB-Defect collapse believable?** Yes. It is verified, not an artefact, and it has a visible mechanism. But PCB-Defect (scanned DIY boards) is so different from AOI crops that it is a domain mismatch, not a fair test of defect generalisation.

**Is the contribution new enough to matter?** As a domain case study with a careful design, yes. As a methods or phenomenon contribution, no.

**Would I cite it?** Yes, as a well-controlled example of group-exposure optimism in industrial detection, with the dose-response result. I would not cite it as evidence about near-duplicates.

**Workshop reviewer?** Accept after reframing and the uncertainty fix.

**Full CV conference?** Reject in current form (one architecture, borderline uncertainty, no human validation, known phenomenon).

**Would I show it to EVREN/SSYZ engineers?** Yes, mainly the source-shift and data-hygiene findings (mirrored duplicates in DsPCBSD+; size/format signatures; group-aware splits) plus the reproducible pipeline. Present the leakage result to them as "a few points", not as a headline.

**Is continuing OpenInspect engineering rational?** Only insofar as it serves the validation listed below. More product engineering does not raise the scientific value. The pipeline is already more than sufficient for the claim.

# Final decision

## **C — WORKSHOP / PREPRINT AFTER SMALL VALIDATION WORK**

Not A: one architecture, no human validation, borderline seed-aware uncertainty, known phenomenon. Not B: the current narrative ("near-duplicate leakage", seed-free CI) would not survive review, and the fix is cheap. Not D or E: the controlled design is sound, the effect is reproducible and graded, and the source-shift result is useful. Three small actions turn this into a defensible workshop paper or preprint.

## Highest-ROI next actions (max 3)

1. **Real human validation, small and targeted.** Two people, blinded, label the 60 probe–mate pairs and 30 control pairs already prepared (`data/pm_items.json`), plus about 60 of the 300 M3 pairs, using the same A–F scale. Report κ against each other and against the AI adjudication. This settles the vocabulary question ("same-family exposure" vs "near-duplicate"), which is currently the paper's largest weakness. Cost: a few hours. No compute.
2. **Two more seeds for D1 (C0-d1 s1/s2, C1-d1 s1/s2) and one more C1-d2 seed.** Five EVREN runs. This resolves whether D1's control shift is noise, and gives every design at least one replicated condition. With these, report a hierarchical (design × seed × group) estimate as the primary interval and the exposure dose-response as the primary analysis.
3. **One larger detector on D0** (e.g. YOLO11s, 3 seeds × C0/C1 = 6 runs). This tests whether the exposure effect scales with capacity, and removes the "single tiny architecture" objection, which is the main barrier between a workshop paper and a full one.
