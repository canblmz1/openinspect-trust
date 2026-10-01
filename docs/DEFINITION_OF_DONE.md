# Definition of Done

A milestone is done only when every item on its list is true and the milestone report (DONE / TEST RESULT / NEXT STEP / BLOCKERS) has been delivered, with the items that genuinely need the maintainer listed.

## Every milestone (M1 onward)

- [ ] New code has type hints and passes `mypy` (strict) and `ruff`.
- [ ] Unit tests cover the new behaviour, including failure paths; no test needs the network or a real dataset.
- [ ] Documentation touched by the change is updated; `CHANGELOG.md` has an entry.
- [ ] No secret, token, personal data or dataset image is committed (`.env` ignored; a pattern scan of the tracked files is clean).
- [ ] Commands in the report were run from the repository root.
- [ ] No dataset archive is downloaded before the ingest milestone, and only for `accepted` sources.

## M0: specification

- [x] Technical specification: [SPEC](SPEC.md)
- [x] v0.1 scope: SPEC §3
- [x] Repository structure: [REPO_STRUCTURE](REPO_STRUCTURE.md)
- [x] Dependency list with licences: [DEPENDENCIES](DEPENDENCIES.md)
- [x] Information format for the first sources: [DATASET_INTAKE](DATASET_INTAKE.md), [`_template.yaml`](../manifests/sources/_template.yaml), four manifests (three accepted, one rejected)
- [x] Licence acceptance checklist and matrix: [LICENCE_CHECKLIST](LICENCE_CHECKLIST.md), [LICENSE_MATRIX](../LICENSE_MATRIX.md)
- [x] Licence evidence archived and hashed: `manifests/evidence/`
- [x] Definition of Done: this file
- [x] Decisions D1–D10 recorded: [DECISIONS](DECISIONS.md) (D3, the code licence, was chosen by the maintainer: Apache-2.0)
- [x] EVREN facts and unknowns recorded: [EVREN](EVREN.md)
- [x] Manifests are structurally identical to the template; class-count and split sums are consistent; every evidence hash matches (checked 2026-09-30)

## M1: source registry

- [x] `openinspect source add` creates a valid manifest (from flags, or from a complete file with `--from-file`), refuses a duplicate slug, never overwrites without `--force`, and cannot create an `accepted` source from flags.
- [x] `openinspect source list` shows slug, status, licence, version, public-release flag; `--json` is machine-readable.
- [x] `openinspect source show SLUG` shows the manifest and its computed flags; `--json` too.
- [x] `openinspect source validate` enforces the schema, the allowlist, evidence hashes and `SHA256SUMS.txt`, slug/file consistency and duplicate slugs; `--release public` blocks any accepted source whose redistribution or derivative-work answer is not `allowed`; exit code 1 on errors.
- [x] Tests: valid accepted manifest; missing licence rejected; missing source URL rejected; invalid DOI is a validation error; unknown redistribution blocks public release; duplicate source ID rejected; accepted source appears in list and show; plus allowlist, evidence and CLI behaviour.
- [x] The committed manifests and evidence pass `openinspect source validate`.
- [x] `configs/licences.yaml` holds the allowlist.
- [x] GitHub Actions runs ruff, mypy, pytest and manifest validation without downloading any dataset (run 36748100561 on commit 65d37f8: all six jobs green, tests and manifest validation on Ubuntu and Windows).
- [x] README states problem, question, method, sources, results and reproduction, without marketing language.

## M2: ingest

- [x] `openinspect ingest download` fetches each accepted archive from the manifest URL, resumes and retries, keeps a file only if its size and the repository's checksum match, computes the SHA-256 and records it in the manifest. Three archives, 388 MB: all matched.
- [x] Archive integrity: the zip CRC-32 of every member passes; extraction refuses unsafe members (T11); the SHA-256 of every extracted file is listed.
- [x] Real counts replace claimed counts: images, boxes, classes and original splits are recomputed from the files and reconciled with each manifest, and the manifests were corrected where they differed (DsPCBSD+ smallest image size, PCB-Defect class strings and size range, PCB-IND per-class counts). No mismatch remains.
- [x] Every image is decoded: 15,278 of 15,278. A corrupt or unopenable file would be listed in the report.
- [x] Annotation formats are identified from the files (COCO, YOLO, VOC as shipped), read in one canonical format and cross-checked against the others (T10); orphan images, orphan annotations and degenerate boxes are reported.
- [x] Exact duplicates (SHA-256): 0 inside each source and 0 across the three.
- [x] The original train/val/test structure is recorded per source; the grouping key is reported as explicit, derived or none with its evidence (T13).
- [x] Licence and attribution stay traceable: each report links to its manifest, states whether the attribution text is present, and quotes what the archive itself says about its licence.
- [x] Adapters were written after inspecting the real archives. Unit tests use small synthetic archives with the same layouts, so no test needs the network or a real dataset; integration tests check the committed reports against the committed manifests.
- [x] No raw data, archive, extracted file or record is committed; everything lives under `OPENINSPECT_DATA_DIR`, outside the repository and OneDrive.
- [x] GitHub Actions ran ruff, mypy, pytest and manifest validation without downloading any dataset (run 36760457834 on commit 29da0e3: all six jobs green, tests and manifest validation on Ubuntu and Windows).

## M3: similarity and leakage audit

- [x] The rules were written before any number was computed ([M3_PROTOCOL](M3_PROTOCOL.md), `8572b7e`) and are unchanged (SHA-256 checked by a test); every later correction, and the eight points of the red-team review, is in [M3_PROTOCOL_AMENDMENT](M3_PROTOCOL_AMENDMENT.md) with the previous rule, the issue, the correction and the effect on interpretation.
- [x] Hash audit inside and across the sources: SHA-256 (0 identical pairs, as in M2), 64-bit pHash and dHash at a published reference distance (3 bits) and at the calibrated one (4 bits).
- [x] Embeddings of all 15,278 images, pinned by revision and weights SHA-256, cached by image SHA-256, model, preprocessing and backend, 0 failures: DINOv2-small (primary, 10.2 images/s in the model) and DINOv2-base (robustness check).
- [x] Exact cosine search; the global top-10 of every image is in `nearest-neighbors.parquet`.
- [x] Thresholds from the frozen rule: group-label pools over all pairs, bootstrap intervals, 3,300 synthetic near-duplicates; the rule's fallbacks and the synthetic recall achieved at the final threshold are reported per source.
- [x] Visual similarity components at two levels with a percolation sweep, cohesion, chaining gap and stability; the chaining rule applied.
- [x] Split leakage per source: crossing components by split pair, affected images and annotations, evaluation images with a training neighbour, the random-split baseline, a group-aware split whose crossings are measured (0), and the sources' own keys across splits.
- [x] Comparison with the sources' own keys (proxy metadata); latent grouping of the source without a key judged by cohesion, stability, pHash agreement, transfer and the second representation.
- [x] Uncertainty: the protocol's bootstrap plus one both-sides check, with a materiality criterion fixed before it ran.
- [x] One representation-robustness check (DINOv2-base), compared by conclusions and partition agreement.
- [x] A dimensional dataset assurance report with explicit rules and evidence, and no scalar score.
- [x] A seeded, stratified review queue of 300 pairs (`review-candidates.csv`, human columns empty) and a local HTML pack with a seeded sample of components; nothing is decided or deleted (T15).
- [x] The core is domain- and platform-agnostic (generic keys; source mapping in `configs/dedup.yaml`).
- [x] Reports in `reports/m3/` rendered from `artifacts/m3/audit.json`; integration tests check reports, digests, thresholds and the frozen protocol without the data.
- [x] Performance recorded: time per stage, images per second, cache size, peak RAM, processor.
- [x] GitHub Actions ran ruff, mypy, pytest and manifest validation without downloading any dataset or model (run 36784716650 on commit 254f79f: all six jobs green, tests and manifest validation on Ubuntu and Windows).
- [ ] The human review of the queue (maintainer, D9): skipped for now by the maintainer's decision (T29); every report states "Human validation: NOT PERFORMED, 0 / 300" and the limitation.

## M4: taxonomy and label quality

- [x] Every source label is mapped exactly once in `configs/taxonomy.yaml` with a status (EXACT, COMPATIBLE, AMBIGUOUS, SOURCE_SPECIFIC, REJECTED) and quoted evidence from the source's paper; the reasoning per class is in [TAXONOMY](TAXONOMY.md) (T30).
- [x] Original labels are immutable: `artifacts/m4/taxonomy-map.parquet` keeps `original_label` next to `normalized_label`, `mapping_status` and `evidence` for all 27,912 boxes, with the generic fields `source_id`, `group_id`, `subgroup_id`, `acquisition_id`, `split`; the mapping is reversible (report table).
- [x] The success question is answered with evidence: four classes (`short`, `open`, `mouse_bite`, `spurious_copper`) are comparable across all three sources; the overlap was not maximised (`copper_burr` stays AMBIGUOUS).
- [x] The cost of the whole-image rule (SPEC 7.4) is measured per source.
- [x] Label-quality checks flag 437 findings as `REVIEW_REQUIRED` (`artifacts/m4/review-required.csv`); nothing is relabelled or dropped (T31).
- [x] `openinspect taxonomy check` runs in CI without data; integration tests check the committed reports against `artifacts/m4/audit.json`, the digests, the taxonomy hash, the original-label counts against the ingest reports and the eligibility rule.
- [x] GitHub Actions ran ruff, mypy, pytest and manifest validation, now including `openinspect taxonomy check`, without downloading any dataset (run 36860398174 on commit ee7ce82: all six jobs green on Ubuntu and Windows).
- [ ] An independent review of the mapping statuses and of the label-quality queue.

## M5: release assembly and canonical splits

- [x] Stable, content-defined global ids `OI_<source>_<12 hex>`, unique by check (T33).
- [x] The crop policy D7 frozen and applied: 939 PCB-Defect crops in native pixels, every rejected anchor recorded with its reason (T32).
- [x] Release v0.1: 4,420 images and 5,297 boxes of 4 classes from 3 sources, no source above 40%, a seeded class-stratified sample; every exclusion recorded in `excluded.parquet` (T34).
- [x] Provenance per item: source, original file id, source version, licence, original and normalized labels, original and canonical split, `group_id`, `subgroup_id`, visual similarity group (`items.parquet`, `annotations.parquet`).
- [x] A0, A1 and one B fold per source in `manifests/splits/v0.1/`; A1 has 0 supplied groups crossing, measured after the split; B excludes training items linked to the held-out source (T35).
- [x] Invariants I1 to I9 pass at build time and in CI from the committed files (`openinspect release check`); I10 holds for the smoke package.
- [x] A machine-readable manifest (`release.json`): sources, versions, licences, counts, taxonomy, split methods and measurements, M3 limitations, the unresolved human validation, hashes, generating commit; `reports/m5/release.md` rendered from it.
- [x] The EVREN smoke package: a deterministic YOLO Detection ZIP of 10/5/5 known A1 items in the data directory, its SHA-256 and the expected split of every item committed before upload (T36).
- [x] GitHub Actions re-checked the committed release with `openinspect release check` on Ubuntu and Windows, without data (run 36860398174 on commit ee7ce82: all six jobs green).
- [x] The import into EVREN and the split-preservation check (M6, below).

## M6: EVREN import smoke test

- [x] The maintainer imported the 20-item YOLO Detection package in the EVREN UI with Auto Split off; the observations are recorded as text in `manifests/releases/v0.1/evren-smoke/observed.yaml` (no screenshot committed).
- [x] `openinspect release smoke-verify` compares every observation with the expectation committed before the upload and, with the data directory, with the ZIP itself: 13 of 13 comparisons MATCH, verdict PASS (`artifacts/m6/evren-smoke-test.json`, `reports/m6/evren-smoke-test.md`).
- [x] The report keeps four kinds of statement apart: observed in EVREN, verified locally, not tested, unknown; EVREN's Dataset Health score is reported as a platform score, not an assurance result.
- [x] `docs/EVREN.md` changes only the facts that were observed (import, classes, split preservation for this package, version creation and freezing, Dataset Health); everything else keeps its status.
- [x] No EVREN training job was started.

## M5.5: training readiness

- [x] A0, A1 and every B fold re-derive exactly from the committed release and configuration (`openinspect readiness check`, in CI).
- [x] A0 − A1 is documented as a descriptive comparison of two test sets; the controlled estimand is C0 − C1 on one common test set, with what changes and what stays constant stated (T39).
- [x] Three seeded C0/C1 designs with the role of every item committed (`manifests/experiments/v0.1/`); C1 exposes no test item and C0 exposes every probe, checked in CI.
- [x] B-natural next to B-strict (the M5 split B, unchanged) for every source; every held-out test set holds exactly its source (T41).
- [x] Representation sensitivity measured on the release with materiality criteria fixed before the computation (T40).
- [x] The PCB-Defect giant component diagnosed by rules fixed before the diagnostics; not cut by hand (T47).
- [x] The 437 M4 findings placed against the release in four categories, with exact counts; nothing relabelled (T42).
- [x] The source identity probe (T44), the negative policy (T45) and the pHash-only pairs (T46) recorded.
- [x] Every package of the M7 plan read by Ultralytics (separate environment) and by a parser that shares no code with the exporter (T43): all 14 packages valid.
- [x] `reports/m5_5/TRAINING_READINESS.md` answers the twelve questions and ends with one verdict decided by a coded rule (T48): **TRAINING READY WITH EXPLICIT LIMITATIONS**.
- [x] The M7 plan written and not executed; no EVREN credits, GPU or training job used.
- [x] GitHub Actions re-derived the M5.5 outputs with `openinspect readiness check` on Ubuntu and Windows, without data (run 36916854075 on commit 230a553: all six jobs green).
- [ ] Human validation of the similarity findings (0 / 300 pairs reviewed).

## v0.1 release

- [x] 3 sources `accepted` with archived evidence; ingest gates G7 and G8 passed (M2, 2026-09-30).
- [ ] `ATTRIBUTION.md` complete.
- [ ] Release has 2,000–5,000 images and 3–5 normalized classes derived from real labels; the mapping is approved and tagged.
- [x] 100% of image and annotation rows pass the provenance validator (SPEC §6.2, I7, I8): `openinspect release check` (M5).
- [ ] 0 repeated SHA-256 in `v0.1-clean`; near-duplicate report published with the calibration evidence (thresholds not arbitrary).
- [ ] Label audit report with reviewed items, reviewer decisions and the unflagged-sample recall estimate.
- [x] Split files for A0, A1 and every leave-one-source-out fold; invariants I1–I9 green in CI, I10 checked when a package is written (M5).
- [ ] `v0.1-raw` and `v0.1-clean` exist and are frozen in EVREN; dataset ids, versions and the SHA-256 of the uploaded ZIPs are recorded; the split-preservation experiment (EVREN.md) passed.
- [ ] E1–E3 done with frozen configs and run records; E4 (RT-DETR) done or explicitly deferred with a reason.
- [ ] Generalization-gap report with confidence intervals, the gap decomposition and per-source rows; every hypothesis reported as supported or not supported.
- [ ] `InferenceProvider` with `LocalProvider` and `EvrenProvider`; the project runs without EVREN access.
- [ ] README, DATA_CARD, PROVENANCE, METHODOLOGY, BENCHMARK, SECURITY, CONTRIBUTING complete.
- [ ] A clean clone reproduces the tables and figures from committed manifests, configs and run records.
