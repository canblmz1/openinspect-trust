<!-- Generated from manuscript.md (single source of truth); do not edit separately. -->

## 10. Limitations

- **No independent human validation.** The relationships between grouped images were characterised only by AI-assisted visual adjudication from one model family. Fine-grained agreement was weak (κ = 0.17).
- **Machine-detected groups.** Groups come from embeddings, perceptual hashes and source metadata. Some links, especially cross-source and board-ID links, are not visually supported.
- **Representation sensitivity.** Group membership changes substantially between DINOv2-small and DINOv2-base.
- **Single architecture and domain.** Only YOLO11n on PCB defect crops was studied. Larger models or other domains may behave differently.
- **Few seeds.** There are 2–3 seeds per design, so seed-only intervals are very wide. D0's probe-minus-control interval includes zero once seed variation is included.
- **Training non-determinism.** Identically configured platform runs differ by 1–2 points on subsets.
- **Mixed replication.** D2's second seed showed no probe-selective gain, and D1's first seed showed a control gain.
- **Weak continuous trend.** The similarity–gain relationship is weak. The exposure strata were defined after the first five seed pairs were evaluated.
- **Design imbalances.** Probes are grouped images and controls are mostly singletons. C0 has 4–6% more training boxes than C1.
- **Source confounding.** Source-held-out results confound acquisition, substrate, resolution and crop generation.
- **No deployment data.** All test images are public-dataset crops; nothing here estimates production-line performance.

