# Ethics and limitations statement

**Ethics.**
- The study uses only public, CC BY 4.0-licensed images of printed circuit boards. It involves no human subjects, personal data or sensitive attributes.
- No new images were collected.
- The work evaluates benchmark reliability; it does not deploy a system.

**Use of AI tools.**
- An AI assistant (Claude) was used to write analysis code, draft text, and carry out the AI-assisted visual adjudication of image pairs.
- The visual adjudication is reported as AI output, with its agreement statistics. It is **not** presented as human or expert validation.
- All numerical results come from deterministic scripts over stored model outputs, and they were re-computed independently.

**Principal limitations** (detailed in the manuscript, Section 10):

1. No independent human validation of the grouped image pairs.
2. Groups are machine-detected, and group membership depends on the embedding model.
3. One architecture (YOLO11n) and one domain (PCB defects).
4. Two to three training seeds per design; training on the platform is not bit-reproducible.
5. Mixed replication: one design's second seed showed no probe-selective gain, and one design's first seed showed a control gain that did not recur.
6. Weak continuous similarity–gain relationship. The exposure strata were defined after five of the eight seed pairs had been evaluated.
7. Source-held-out results confound acquisition, substrate and preprocessing differences; source identity is trivially predictable.
8. No deployment or production-line data.

**Misuse considerations.** The results should not be read as a performance estimate for any production inspection system, nor as evidence about the quality of any specific dataset provider.
