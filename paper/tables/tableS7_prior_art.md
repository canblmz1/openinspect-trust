# Table S7. Closest prior work vs this study (from abstracts / landing pages; see paper/CITATION_AUDIT.md)

| work | task | leakage unit | fixed common test set across conditions | controlled exposure manipulation | within-test negative control | multiple training seeds | source/domain-held-out arm |
|---|---|---|---|---|---|---|---|
| Barz & Denzler 2020 [1] | classification | near-duplicate images | no (test set purged) | no | no | not central | no |
| Laroca et al. 2023 [2] | licence-plate recognition | same plate | no (fair split) | retraining on fair split | no | multiple models | no |
| Tampu et al. 2022 [3] | OCT classification | subject/volume | no | split strategy | no | repeated | no |
| Figueiredo & Mendes 2024 [4] | video object detection | correlated frames | no | split strategy | no | not verified | no |
| Babu et al. 2024 [6] | automotive object detection | injected test images | yes | yes (injection rate) | no | repeated (not verified in detail) | no |
| DataSAIL 2025 [5] | biomedical ML | similarity | no | splitting tool | no | — | out-of-distribution splits |
| this study | PCB object detection | machine-detected visual-similarity groups | yes (byte-identical) | yes (group-mates vs matched replacements) | yes (unexposed controls) | 8 matched seed pairs | yes |
