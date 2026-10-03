# Reproducibility statement

**Released** (public repository, Apache-2.0 code):

- **Data pipeline.** Source registry with licence evidence (SHA-256-archived records), ingest and taxonomy code, release manifest (v0.1: 4,420 images, per-item SHA-256, crop parents), and every split and design manifest (A0, A1, B-strict, B-natural, C0/C1 for D0–D2, probe/control roles).
- **Configuration.** The single training configuration used by all 31 platform jobs, including the two deviations from the original plan (`cos_lr = True`, `label_smoothing = 0.1`), applied identically to every run.
- **Run record.** A public, ID-free run inventory (`reports/m7_final/public/RUN_INVENTORY_PUBLIC.csv`): run alias, condition, seed, status (cancelled and duplicate attempts kept), role in the study, checkpoint SHA-256 and effective-configuration hash.
- **Evaluation.** Evaluation code (Ultralytics 8.3.0; imgsz 640, conf 0.001, IoU 0.7, max_det 300) and the analysis code that produces every number in the paper (`reports/m7_final/scripts/`).
- **Fixed analysis settings.** Pre-specified primary endpoint; bootstrap 2,000 draws (seed 20261003); placebo 10,000 relabellings (seeds 1000–1002).
- **Outputs.** Per-image detections for every evaluated model (stored outside the repository; can be published as a data supplement) and the frozen output CSVs with their SHA-256 hashes (`reports/m7_final/FINAL_FREEZE_MANIFEST.md`).

**Verification performed.**

- Every model's overall mAP50-95 was reproduced by two independent evaluation paths (the stored-detection evaluator and plain `YOLO.val`), with differences below 0.0001 points.
- The final analysis was re-run from the sanitised public scripts, and the outputs were compared with the frozen CSVs (see the freeze manifest).

**Not bit-reproducible.**

- Training was done on a managed cloud platform. Two identically configured runs differed by 1.13 mAP50-95 points overall and 2.22 points on control images. Retraining from the published configuration and seeds will reproduce the design, not the exact numbers.
- Model weights are not redistributed (see `DATA_AVAILABILITY.md`). Checkpoints are identified by SHA-256.

**Not performed.** Independent human validation of the grouped image pairs. The AI-assisted visual adjudication labels and the blinded review sheets' keys are released, so human raters can repeat the review on the same pairs.
