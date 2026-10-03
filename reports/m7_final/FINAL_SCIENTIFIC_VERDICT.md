# OpenInspect-Trust M7: final scientific verdict (study frozen 2026-10-03)

**AI visual adjudication was performed; independent human validation was not performed.**

## What was done in this closure step

- Refreshed the EVREN inventory read-only, matching runs by dataset version + seed + condition (not run name). Before the new jobs it held 26 jobs and 17/17 valid; now it holds 31 jobs (public, ID-free: `public/RUN_INVENTORY_PUBLIC.csv`; the raw inventory with platform IDs stays private).
- Determined the minimum missing runs: **5**. D1 needed C1-s1, C0-s2 and C1-s2, because C0-d1-s1 already existed twice; D2 needed a full seed-1 pair. D0 was not rerun.
- The maintainer launched the 5 jobs in the EVREN UI, following the repository rule that training is started only in the UI. All completed. The requested configuration is identical across all 31 jobs; effective-configuration hash `d021d7fa…` and requested hash `44caf38b…` equal the M7 runs; Ultralytics 8.3.0.
- Downloaded only the PyTorch best.pt of the 5 jobs; verified size, SHA-256, job ID in `train_args` and seed (public hashes: `public/CHECKPOINT_MANIFEST_PUBLIC.csv`).
- Evaluated locally with the unchanged M7 evaluator (imgsz 640, conf 0.001, iou 0.7, max_det 300). An independent plain-`val` re-run matched to 4 decimals. No EVREN inference was used.
- Final analysis: `scripts/final_analysis.py`, with choices pre-registered in its header before the new results were seen.

## Answers

1. **Does D0 still reproduce?** Yes, exactly (unchanged models and test set; two independent evaluators agree).
2. **Does the seed-aware D0 probe effect (the primary estimand) remain positive?** Yes: +3.91, combined two-stage 95% interval **+0.41 to +7.65** (P(≤0) = 0.014). The seed-only interval with 3 seeds (−1.8 to +9.6) does not exclude zero.
3. **Does probe − control remain convincing?** Moderately. D0 alone: +4.08, combined −0.97 to +9.07 (P = 0.07); placebo p = 0.013. Pooled over the three designs: **+3.4 (+0.7 to +6.1)**. Positive in 8/8 seed pairs, but two of them are about zero.
4. **Did the new D1 seeds explain the anomaly?** They showed that it did not recur (outcome A). D1 controls went +3.09 → −0.75, −1.68 (mean +0.22), and D1 probe − control is now +3.81 (placebo p = 0.009). Training stochasticity of the first run is a plausible but unproven explanation.
5. **Does D2 support D0?** Only partly. Seed 0 did (+4.58), but seed 1 shows probes and controls rising equally (+1.69 / +1.68; probe − control +0.01). D2 mean +2.30, placebo p = 0.08, combined interval includes zero. D2 is now the weakest design.
6. **Does the dose-response survive?** In binned form, yes, and it was confirmed out of sample. Probes with exposure Δ > 0.08 gain +6.85 on average across the 8 seed pairs, all positive (min +4.5), including the 3 new runs (+10.0, +5.7, +4.5). Weakly exposed probes gain about 0, like controls. In continuous form it is weak (Spearman 0.08–0.15; only D0 excludes zero). Wording: "gains were concentrated among the most strongly exposed test images and were directionally larger at higher visual similarity".
7. **Does DINOv2-base support the same trend?** Yes for the binned contrast (top-bin means +6.6 / +10.4 / +7.4, every seed ≥ +5.9). The continuous correlations are similarly weak (0.11–0.13).
8. **Is "group exposure" the correct terminology?** Yes: "train–test group exposure" (machine-detected visual-similarity groups). It is not near-duplicate, duplicate or same-board leakage.
9. **Is human validation still a material limitation?** Yes. The two AI passes agree at κ = 0.17 on fine categories; it is the same model, and no person has looked. It does not undermine the C0/C1 effect, which does not depend on the labels, but it limits every claim about *what kind* of relationship drives it. Two raters on the 90 prepared pairs would take a few hours.
10. **Is source shift the stronger practical problem?** Yes, by an order of magnitude: −27 to −47 points versus about +2 overall and about +4 on probes.
11. **Is a workshop paper justified?** Yes. A controlled fixed-test design, 8 seed pairs over 3 independently drawn designs, negative controls, placebo tests, an exposure-strength analysis and a source-shift contrast, with honest limits.
12. **Is an arXiv preprint justified?** Yes, under the terminology and limitations in `FINAL_SAFE_CLAIMS.md`.
13. **Would I stop additional model training now?** **Yes.** More YOLO11n seeds would narrow intervals only slowly. A second architecture (YOLO11s) would materially raise value for a *full* conference paper, not for the workshop or preprint. Defer it until reviewers ask or a full-paper target is chosen.
14. **Is the study ready to send to EVREN/SSYZ engineers for technical feedback?** Yes, as a technical report. It is most useful to them for the source-shift finding, the run-to-run non-determinism of identically configured jobs (1–2 points), the run-name and dataset-mismatch hazards seen in M7, and the reproducible audit pipeline.

## Decision

## **B — WORKSHOP / PREPRINT READY**

**Why B and not C:**
- The remaining small validation work (5 replication runs) has been done. D1's control anomaly did not recur, and the strongest-exposure stratum held in the out-of-sample runs; D2 weakened, which is reported.
- The claims are calibrated: modest effect, seed-aware intervals, AI-not-human disclosure, and D2 seed 1 reported as is.

**Why not A:**
- one architecture, one domain;
- 2–3 seeds per design;
- D0 probe − control does not exclude zero on its own with seed variance;
- no human validation;
- the phenomenon is known prior art.

**Strongly recommended before submission, but not a precondition for posting a preprint:** blinded labelling of the 90 prepared pairs by two people (no compute).

## Stop condition

The study is frozen. Experiment status: FROZEN — NO FURTHER TRAINING PLANNED. No further experiments are started. YOLO11s is **not** launched: it would help a full-paper submission, not this workshop/preprint.
