# Decision log

Decisions D1–D10 come from [SPEC §12](SPEC.md); T1–T7 are technical choices made while building M1. Each has the same five fields. All were taken on 2026-09-30 under the maintainer's autonomous-execution directive. **D3, the code licence, is the exception: the maintainer chose it (Apache-2.0).**

## D1 — Domain
- **Decision:** PCB surface-defect detection with bounding boxes.
- **Evidence:** three box-annotated sources with CC BY 4.0 confirmed by three archived records each (repository record, DataCite, Crossref); no other domain produced three ([LICENSE_MATRIX](../LICENSE_MATRIX.md)).
- **Reason:** it satisfies the v0.1 scope and the licence gates.
- **Risk:** results are PCB-specific (SPEC R9); two of three sources share a modality (R2).
- **Revisit when:** a source fails the ingest gates, or a verified source from another domain appears.

## D2 — Sources
- **Decision:** `dspcbsd-plus`, `pcb-ind` and `pcb-defect` are `accepted`; `deeppcb` is `rejected` (DO NOT USE).
- **Evidence:** [manifests/sources/](../manifests/sources/) and [SHA256SUMS.txt](../manifests/evidence/SHA256SUMS.txt). DeepPCB: the archived README limits the dataset to research purposes while the archived LICENSE file is MIT.
- **Reason:** admission gates G1–G6 and G9 pass for the three; DeepPCB's terms give no reliable clarity on redistribution of the dataset.
- **Risk:** independence of the two factory-AOI sets rests on affiliations only; ingest gates G7 and G8 are still open.
- **Revisit when:** the cross-source duplicate audit (M3) finds shared images, a record's licence changes, or the archive reconcile at M2 fails.

## D3 — Code licence
- **Decision:** Apache-2.0 for the code, chosen by the maintainer on 2026-09-30. `LICENSE` holds the unmodified licence text; `pyproject.toml` declares `license = "Apache-2.0"`.
- **Evidence:** the maintainer's instruction; the `LICENSE` text is word-for-word identical to the copy served by the GitHub licences API and to the text published at apache.org; dependency licences are compatible ([DEPENDENCIES](DEPENDENCIES.md)); the AGPL isolation of Ultralytics holds under this choice.
- **Reason:** a permissive licence with an explicit patent grant suits an open research tool.
- **Risk:** the datasets are not covered by this licence; they keep their own (CC BY 4.0 for the accepted sources, see D4). Ultralytics stays an optional, never-bundled extra.
- **Revisit when:** an institution or contributor requires another licence; relicensing needs the consent of all copyright holders.

## D4 — Dataset release licence
- **Decision:** provisional CC BY 4.0 for the compiled dataset. No public dataset release before the release checklist (R1–R6 in [LICENCE_CHECKLIST](LICENCE_CHECKLIST.md)) passes.
- **Evidence:** all three inputs are CC BY 4.0; CC BY 4.0 permits adaptation with credit and change indication, and forbids adding restrictions.
- **Reason:** the compilation may not be more restrictive than its inputs; CC BY 4.0 is the matching choice.
- **Risk:** attribution errors; EVREN's terms for third-party uploads are unverified.
- **Revisit when:** a source is replaced by an NC or SA one, or before publishing on EVREN.

## D5 — Schema deviations from brief §11
- **Decision:** accept plural `original_labels`/`normalized_labels` plus a per-box annotation file, `source_group_id`, `parent_id`/`crop_xyxy`, and two hashes (`sha256`, `sha256_source`).
- **Evidence:** brief §36 requires a grouped-object leakage check and §12 requires normalisation provenance; detection images carry several boxes (DsPCBSD+ 20,276 boxes on 10,259 images; PCB-IND 5,932 on 4,789; PCB-Defect 1,704 on 230).
- **Reason:** the brief's singular fields cannot represent detection data without losing provenance.
- **Risk:** field names differ from the brief's literal example.
- **Revisit when:** a consumer needs the literal §11 record: add an export adapter.

## D6 — Locations
- **Decision:** the repository stays where it is (risk recorded). Raw data goes outside OneDrive and outside the repository under `OPENINSPECT_DATA_DIR` (suggested `C:\data\openinspect`). The virtual environment lives outside OneDrive too (`UV_PROJECT_ENVIRONMENT`).
- **Evidence:** the folder is under `%USERPROFILE%\OneDrive\Desktop`; C: is the only drive, about 40 GB free (92% used).
- **Reason:** the maintainer said not to stop for this; OneDrive risks (sync conflicts, locked files, `.git` corruption) are real but manageable if data and the environment stay out.
- **Risk:** OneDrive syncing `.git` and any `.venv` created inside the folder.
- **Revisit when:** the first sync conflict, or before M2's first download. Moving the repo to `C:\dev\openinspect-trust` removes the risk.

## D7 — Scale and crop policy
- **Decision:** keep native resolution; cut large images (`pcb-defect`) into ROI crops of about 300×300 around annotations; freeze the exact policy in M2 with a sensitivity check.
- **Evidence:** native sizes 226×226 (`dspcbsd-plus`), 300×300 (`pcb-ind`), 800×600 to 6000×4000 (`pcb-defect`); nominal pixel pitch of the AOI set is 6–12 µm/px, of the scanner set 15.9 µm/px if unresized.
- **Reason:** resizing large images would shrink small defects; ROI crops mimic how the AOI sets were built.
- **Risk:** crop policy changes defect pixel size and results (SPEC R3).
- **Revisit when:** M2 inspection of real images shows a pixel-pitch difference above about 2×.

## D8 — EVREN facts
- **Decision:** use the maintainer-supplied facts in [EVREN](EVREN.md); keep two items UNKNOWN (split preservation on ZIP import, inference `max_det`); code against no EVREN API except inference.
- **Evidence:** the maintainer's statement from the EVREN user guide. The public explore page returned no documentation to an automated fetch.
- **Reason:** the maintainer answered the questions D8 listed; the rest cannot be settled from documents.
- **Risk:** an unverified fact may be wrong; the local manifest stays canonical so a wrong assumption cannot leak into results.
- **Revisit when:** the first small EVREN import (M6) and the API snippet review.

## D9 — Human review budget
- **Decision:** default of about 300 label items and about 300 calibration pairs, reviewed by the maintainer, prioritised by the audit.
- **Evidence:** none yet; it is a default for a dataset of at most 5,000 images.
- **Reason:** threshold calibration and audit-recall estimates need a few hundred human labels to be meaningful.
- **Risk:** the maintainer's time; without it calibration falls back to synthetic positives and hard negatives only.
- **Revisit when:** M3 starts, when the maintainer's actual availability is asked.

## D10 — Analysis defaults
- **Decision:** non-inferiority margin δ = 0.02 mAP50 for H3; 1,000 bootstrap resamples; three seeds (one in the minimal variant).
- **Evidence:** none yet; the seed-to-seed variance is measured in the M7 pilot.
- **Reason:** pre-registration needs numbers before results exist; two points is conservative for a small dataset.
- **Risk:** δ may be too tight or too loose relative to the real variance.
- **Revisit when:** after the pilot, before the tag `analysis-plan-v0.1`.

## T1 — Type checker: mypy (strict)
- **Decision:** mypy in strict mode with the Pydantic plugin.
- **Evidence:** mypy installs as pure Python; Pydantic v2 ships a mypy plugin; pyright's Python wrapper downloads a Node.js runtime at first use.
- **Reason:** fewer moving parts in CI and on the maintainer's machine.
- **Risk:** mypy is slower and a little less precise than pyright on large codebases.
- **Revisit when:** the codebase passes a few thousand lines, or the plugin causes false positives.

## T2 — Python 3.12 only
- **Decision:** `requires-python >=3.12`; CI on Ubuntu and Windows with 3.12.
- **Evidence:** the dev machine runs 3.12.10 and the maintainer named Python 3.12.
- **Reason:** one version means one tested configuration.
- **Risk:** users on older interpreters cannot install it.
- **Revisit when:** a collaborator needs another version.

## T3 — CLI and schema stack
- **Decision:** Typer for the CLI, Pydantic v2 (`extra="forbid"`, frozen) for manifests, PyYAML `safe_load` for reading.
- **Evidence:** the maintainer named Typer and Pydantic.
- **Reason:** `extra="forbid"` catches misspelt keys; frozen models avoid accidental mutation.
- **Risk:** none notable.
- **Revisit when:** the schema needs versioned migrations.

## T4 — Two tiers of acceptance
- **Decision:** `accepted` admits a source for download and internal use; public release needs redistribution and derivative_work `allowed`, and an unclear answer blocks it (`validate --release public`).
- **Evidence:** the maintainer's M1 test list ("unknown redistribution permission → public release blocked"); brief §22 forbids public release when compatibility is uncertain but does not forbid internal use.
- **Reason:** matches the brief and the requested behaviour.
- **Risk:** an accepted source might be mistaken for releasable; `list` shows a public-release column and `validate` warns.
- **Revisit when:** a source with a non-allowlisted licence is considered.

## T5 — Evidence integrity
- **Decision:** evidence snapshots are stored byte-for-byte (`manifests/evidence/** -text` in `.gitattributes`), hashed in `SHA256SUMS.txt`, and verified by `openinspect source validate`.
- **Evidence:** git's `text=auto` would rewrite line endings of JSON snapshots and change their hashes across operating systems.
- **Reason:** reproducible, tamper-evident licence evidence.
- **Risk:** snapshots (e.g. Mendeley's `download_expiry_time`) change on every fetch, so a re-download never hashes the same; a snapshot is evidence of a moment, not a reproducible artefact.
- **Revisit when:** evidence grows large; then store it outside git with only the hashes tracked.

## T6 — CI supply chain
- **Decision:** GitHub Actions are pinned to full commit SHAs, with the release tag in a comment; CI runs on Ubuntu and Windows.
- **Evidence:** latest releases looked up on 2026-09-30 (`actions/checkout` v7.0.1, `astral-sh/setup-uv` v10.2.0).
- **Reason:** a moving tag can be retargeted; a SHA cannot.
- **Risk:** pins go stale; Dependabot or a manual bump is needed.
- **Revisit when:** a security advisory affects a pinned action.

## T7 — Branching
- **Decision:** work directly on `main`; no pull requests while there is a single maintainer.
- **Evidence:** the maintainer's instruction to commit and push `main`.
- **Reason:** speed; CI still runs on every push.
- **Risk:** no review gate.
- **Revisit when:** a second contributor joins.
