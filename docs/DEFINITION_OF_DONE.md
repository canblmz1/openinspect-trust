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
- [x] Decisions D1–D10 recorded: [DECISIONS](DECISIONS.md) (D3, the code licence, is a legal choice left to the maintainer)
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
- [ ] GitHub Actions runs ruff, mypy, pytest and manifest validation without downloading any dataset.
- [x] README states problem, question, method, sources, results and reproduction, without marketing language.

## v0.1 release

- [ ] 3 sources `accepted` with archived evidence, ingest gates G7 and G8 passed; `ATTRIBUTION.md` complete.
- [ ] Release has 2,000–5,000 images and 3–5 normalized classes derived from real labels; the mapping is approved and tagged.
- [ ] 100% of image and annotation rows pass the provenance validator (SPEC §6.2, I7, I8).
- [ ] 0 repeated SHA-256 in `v0.1-clean`; near-duplicate report published with the calibration evidence (thresholds not arbitrary).
- [ ] Label audit report with reviewed items, reviewer decisions and the unflagged-sample recall estimate.
- [ ] Split files for A0, A1 and every leave-one-source-out fold; invariants I1–I10 green in CI.
- [ ] `v0.1-raw` and `v0.1-clean` exist and are frozen in EVREN; dataset ids, versions and the SHA-256 of the uploaded ZIPs are recorded; the split-preservation experiment (EVREN.md) passed.
- [ ] E1–E3 done with frozen configs and run records; E4 (RT-DETR) done or explicitly deferred with a reason.
- [ ] Generalization-gap report with confidence intervals, the gap decomposition and per-source rows; every hypothesis reported as supported or not supported.
- [ ] `InferenceProvider` with `LocalProvider` and `EvrenProvider`; the project runs without EVREN access.
- [ ] README, DATA_CARD, PROVENANCE, METHODOLOGY, BENCHMARK, SECURITY, CONTRIBUTING complete.
- [ ] A clean clone reproduces the tables and figures from committed manifests, configs and run records.
