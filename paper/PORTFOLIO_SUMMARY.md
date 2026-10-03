# OpenInspect-Trust: portfolio summary

**What it is.** OpenInspect-Trust is a reproducible "benchmark assurance" project for industrial computer vision. It checks whether a defect-detection benchmark can be trusted before and after expensive model training, using three public printed-circuit-board (PCB) defect datasets as the case study.

## What I built and did

- **Multi-source dataset provenance.** I ingested three public datasets with archived licence evidence (SHA-256-hashed registry records). I mapped their taxonomies to a shared four-class scheme and built a versioned release of 4,420 images in which every image traces back to its source file and crop.
- **Split assurance.** I implemented exact and perceptual hashing plus DINOv2 embedding similarity, with thresholds fixed by a pre-committed rule. These produce visual-similarity groups and group-aware train/test splits, with leakage invariants checked in continuous integration.
- **Controlled experiment design.** I designed a fixed-test-set experiment. Two training sets differ only in whether related ("group-mate") images of selected test images are included, and unexposed test images act as a negative control. Three independent designs and source-held-out splits were included.
- **Training orchestration on a cloud platform.** I ran 31 YOLO11n training jobs on the EVREN platform. I audited them read-only through its API: runs were matched by dataset version and seed rather than run name, which caught several mislabelled jobs, and the effective configuration was verified from each checkpoint.
- **Local reproducible evaluation.** One evaluator was used for every model. Per-image predictions are stored, and an independent second evaluation path reproduced every score to 1e-4.
- **Uncertainty analysis.** I reported test-sampling, training-seed and combined uncertainty separately, ran 10,000-draw placebo tests, and pooled the designs. I added replication seeds only where the evidence was ambiguous (5 extra jobs, the minimum needed).
- **Red-team review and claim correction.** I ran an adversarial internal review, including blinded AI-assisted visual adjudication of image pairs. It overturned the original framing ("near-duplicate leakage"): no near-duplicates were found, so the finding was renamed "train–test group exposure", and claims were downgraded to what the evidence supports. Negative and mixed results stay in the main text.

## What the research found (stated conservatively)

- Training on related images raised accuracy on the exposed test images by about 3.7 mAP50-95 points, but only about 2 points on the whole test set. Replication across designs was mixed.
- Evaluating on an unseen source cost 27–47 points, an order of magnitude more.

**Limitations.** No independent human validation was performed; one model architecture and one domain were studied.

**Status.** The study is frozen. A workshop/preprint draft is prepared but has not yet been submitted or accepted.

**Skills.** Python, PyTorch/Ultralytics, DINOv2 embeddings, statistics (bootstrap, permutation tests), experimental design, data provenance and licensing, CI-checked reproducibility, cloud ML platform APIs, scientific writing.
