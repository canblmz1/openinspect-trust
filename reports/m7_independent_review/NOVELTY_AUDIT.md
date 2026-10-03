# Novelty audit

| dimension | assessment |
|---|---|
| **Phenomenon** | **Not novel.** Near-duplicate, group and patient leakage inflating test performance is well documented (Barz & Denzler; Laroca et al.; Tampu et al.; automotive leakage studies). The M7 finding is a confirmation in a new domain, and a modest one: +1.8 pp overall. |
| **Method** | **Low novelty.** DINOv2 + pHash similarity graphs, threshold calibration on synthetic transforms and group-aware splitting are standard (cf. DataSAIL for similarity-aware splits; embedding dedup in many dataset audits). The audit tooling is well engineered but not methodologically new. |
| **Experimental design** | **Moderately uncommon.** A matched counterfactual (C0/C1) on one byte-identical test set, with naturally occurring group-mates swapped for profile-matched replacements, an in-test probe/control contrast, multiple designs and seeds, cluster-paired uncertainty and a source-held-out arm *together* is more careful than most leakage papers. Each ingredient has precedents: controlled injection on a fixed test set in automotive YOLO work, and per-subject vs per-image splits in OCT. The probe/control-with-exposure-dose analysis (added in this review) is the most distinctive element. |
| **Dataset-specific** | **Some.** First (to my search) controlled leakage measurement on public PCB defect datasets. Also: the observation that DsPCBSD+ holds mirrored copies across its own train and val folders, and that PCB-IND crops of one board ID drive the largest exposure gain. Useful to PCB practitioners; narrow audience. |
| **EVREN context** | **Not scientific novelty.** Training on EVREN is an execution environment. It matters for reproducibility claims (non-bit-exact training) and for Turkish industrial relevance, not for novelty. |
| **Tooling** | **Practical value, not research novelty.** Reproducible release, export checks and readiness checks in CI are good engineering, and reviewers will value the artifact. That is not a scientific contribution. |

## Is the combination meaningfully uncommon?

PCB object detection + machine-detected similarity groups + controlled C0/C1 on a matched test population + exposed probe vs unexposed control + multi-seed + paired uncertainty + source-held-out: **yes, the full combination appears uncommon.** I found no prior work doing all of it. The closest design (the automotive YOLO leakage-injection study) uses synthetic copies, not natural groups, and has no probe/control split.

It is not "better done elsewhere". It is "parts done elsewhere, combined here, in a niche domain, with a small effect". The combination is a solid *case-study* contribution. It is not a methods contribution.

## What would make it more novel

The exposure dose-response (gain rising with feature-space proximity of the exposing training item, replicated across designs and two embeddings) is a cleaner and more general finding than the binary probe/control result. Building the write-up around "graded exposure, not binary duplicate status, predicts optimism" would give the paper a sharper claim. It would also be more defensible given that visually only 8% of probe–mate pairs are duplicate-like.
