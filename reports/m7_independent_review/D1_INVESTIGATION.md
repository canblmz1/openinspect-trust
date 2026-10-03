# D1 investigation: why did the controls move?

> **Pre-replication record, superseded 2026-10-03.** The final numbers are in `reports/m7_final/` (5 replication runs added; the analysis was re-run with 2,000 bootstrap draws and 10,000 placebo relabellings, so intervals differ from those below). Do not cite numbers from this file; see `reports/m7_final/FINAL_SCIENTIFIC_VERDICT.md`.

D1 (one seed): overall +3.70, probe +3.94, control +3.09, probe − control +0.84 pp. All values reproduced exactly.

## Hypotheses tested

| hypothesis | test | result |
|---|---|---|
| Design-generation bug (controls actually exposed) | Constraint groups of controls in C0 train: 0. Feature-space Δ (max cos to C0 train − C1 train) for controls: mean 0.002; 5 controls > 0.02 (D0: 14, D2: 13) | **Rejected.** D1 controls are the *least* exposed of the three designs. |
| Package or test mismatch | C0-d1 / C1-d1 test files byte-identical (816 files); train differs exactly by mates/replacements | **Rejected.** |
| Different source or class mix of controls | Controls 89 / 41 / 85 (DsPCBSD+ / PCB-Defect / PCB-IND) vs D0 89 / 39 / 85; boxes mouse_bite 103, spurious 63, open 46, short 29 | Small differences only. Not explanatory. |
| Replacement profile | mates vs replacements D1: identical sources and formats; boxes 268 vs 258 (C0 +10, open +6, short +2, spurious +3, mouse_bite −1) | Same direction and size as D0/D2. Not explanatory. |
| Group structure of controls | Singletons 129 (D0 141, D2 135); one 41-item group (PCB-Defect) | Similar to D0. |
| Where the control gain sits | Control C0 − C1 by source: DsPCBSD+ +2.65, PCB-Defect +1.03, **PCB-IND +4.97**; by class: **short +8.7**, mouse_bite +4.1, spurious +3.5, open −3.9; singleton controls +5.67, grouped +2.64 | Broad, not one cell. Concentrated in PCB-IND and the short class, the same cells that carry probe gains in D0. |
| Training noise | Two identically configured replicates of C0-d1-s1 on the D1 test set differ by +1.13 overall and **+2.22 on controls**. Replicate − C1-d1-s0: controls +2.53 and +0.32 | **Plausible.** The D1 control shift (+3.09) is 1.4× the one observed replicate-to-replicate control difference and about 2.6× the D0 same-condition control RMS (1.19). |
| Exposure effect still present in D1? | Probes by exposure strength: Δ < 0.02 **+0.73**, 0.02–0.08 +3.36, Δ > 0.08 **+7.43** (base embedding: +13.65) | **Yes.** Strongly exposed probes gain far more than controls; weakly exposed probes gain less than controls. |

## Reading

- No bug, leakage or construction difference explains D1. Its controls are, if anything, *better* isolated than D0's.
- The overall C0 − C1 shift in D1 behaves like a model-level offset: C0-d1-s0 is the highest-scoring C0 model (54.48), and the two C0-d1-s1 replicates score 54.52 and 53.39. That pattern is compatible with "C0 happened to train into a better optimum", which lifts every subset. With one C1 seed and no C1-d1 replicate, this cannot be separated from a genuine design effect.
- The simple causal story ("only exposed items move") is **not** supported in D1. The graded story is: exposure strength predicts gain *on top of* a model-level offset. D1 is consistent with that, because its strongly exposed probes still stand out (+7.4 vs +3.1 for controls).
- Status: **unresolved.** The most likely explanation is training variation in one seed, and the replicate data support it, but one seed cannot prove it. The D1 result must stay in the paper as evidence that C0 − C1 overall gains are not reliably confined to probes.

## What would resolve it

Two more seeds each of C0-d1 and C1-d1 (4 runs). If the control contrast averages near zero, D1 joins D0/D2. If it stays near +3, the control/probe separation is design-dependent and the claim must be weakened to "exposure-graded gains on top of design-level shifts".
