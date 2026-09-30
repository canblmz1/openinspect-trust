# Decision log

Decisions D1–D10 come from [SPEC §12](SPEC.md); T1–T7 are technical choices made while building M1, T8–T14 while building M2, T15–T23 while building M3. Each has the same five fields. All were taken on 2026-09-30 under the maintainer's autonomous-execution directive. **D3, the code licence, is the exception: the maintainer chose it (Apache-2.0).**

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
- **Risk:** independence of the two factory-AOI sets rests on affiliations only. The ingest gates G7 and G8 passed on 2026-09-30 (M2) and no exact duplicate exists across the three sources, but near-duplicates across sources are not measured before M3.
- **Revisit when:** the cross-source near-duplicate audit (M3) finds shared images, or a record's licence changes.

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
- **Revisit when:** the first sync conflict. M2's data went to `C:\data\openinspect` (0.9 GB: archives, extracted files, records), outside both the repository and OneDrive, and `ingest` refuses a data directory inside either. Moving the repo to `C:\dev\openinspect-trust` removes the remaining risk.

## D7 — Scale and crop policy
- **Decision:** keep native resolution; cut large images (`pcb-defect`) into ROI crops of about 300×300 around annotations; freeze the exact policy at the start of M5 (release assembly) with a sensitivity check.
- **Evidence:** native sizes measured at ingest: 226×226 (`dspcbsd-plus`; 111 of its images are 108×108), 300×300 (`pcb-ind`), 1540×1285 to 5971×5236 (`pcb-defect`); nominal pixel pitch of the AOI set is 6–12 µm/px, of the scanner set 15.9 µm/px if unresized.
- **Reason:** resizing large images would shrink small defects; ROI crops mimic how the AOI sets were built.
- **Risk:** crop policy changes defect pixel size and results (SPEC R3).
- **Revisit when:** a pixel-pitch difference above about 2× is shown. M2 could not test this: no image carries EXIF or a DPI value, so the pitch stays unknown for all three sources. The policy is frozen at the start of M5, not in M2, because crops and their parent images must enter the split definition together (T8).

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

## T8 — Global ids are assigned at release assembly
- **Decision:** ingest records are keyed by (`source_dataset`, `source_item_id`) and carry no `OI_%06d` id. The id is assigned when a release is assembled (start of M5) by sorting the final pool as SPEC §6.2 defines. Format normalisation and the crop policy (D7) move there too.
- **Evidence:** an id defined by sort order over all sources changes whenever a source or an item is added, while ingest processes and re-runs one source at a time; crops need parent ids that exist only once the pool is fixed.
- **Reason:** an identifier that can still shift must not be handed out.
- **Risk:** code written before M5 must not assume an `id` field; the record type has none.
- **Revisit when:** a consumer needs stable ids before M5.

## T9 — What an ingest puts in git
- **Decision:** the per-file SHA-256 list, the image records and the annotation records (about 23 MB for the three sources) live in `<data dir>/records/<slug>/` and are regenerable. Git tracks `manifests/ingest/<slug>/report.json` (counts, classes, splits, grouping evidence, anomalies, reconciliation, and the SHA-256 of each record file), `download.json`, `manifests/ingest/cross_source.json` and `reports/m2-ingest-report.md`. `acquisition.sha256_manifest` points to the report. This replaces the planned `manifests/sha256/` and `manifests/images/` for M2.
- **Evidence:** the hash lists have about 55,000 lines and the image records 15,000; committing them would put generated text into every adapter change, while the archive SHA-256 plus deterministic adapters reproduce them (a test runs the pipeline twice and compares the output byte for byte).
- **Reason:** small diffs, and reproducibility proved by digests instead of copies.
- **Risk:** the records are not in git; a different archive version changes the digests, which is the intended alarm.
- **Revisit when:** a release needs per-image provenance in git; release assembly then writes `manifests/images/`.

## T10 — One canonical annotation format per source
- **Decision:** each adapter reads one canonical format and cross-checks the others: `dspcbsd-plus` COCO (YOLO cross-check), `pcb-ind` YOLO (COCO and VOC cross-check), `pcb-defect` COCO (the only format).
- **Evidence:** measured at ingest. PCB-IND's YOLO labels hold all 5,932 boxes, the paper's total; the COCO file lacks one (val `5799_t_038`, zero height) and one VOC file (`6194_b_017.xml`, train) is empty. DsPCBSD+ COCO and YOLO agree (no anomaly raised).
- **Reason:** a format that drops a box cannot be the reference; disagreements are reported as anomalies instead of being repaired silently.
- **Risk:** YOLO stores no image size and no per-box id; sizes come from the decoded image.
- **Revisit when:** a source publishes a corrected version.

## T11 — Archives are untrusted input
- **Decision:** extraction refuses path traversal, absolute paths, drive letters, reserved Windows names, case-insensitive name collisions and symlinks, enforces member-count and size limits, writes into a `.partial` directory that is renamed on success, and verifies the CRC-32 of every member. XML is parsed with `defusedxml`. A file in an archive that is not data (DsPCBSD+ ships `Hash.py`) is read as text and never executed.
- **Evidence:** the three archives come from public repositories and raised no extraction anomaly; the checks cost seconds.
- **Reason:** third-party archives are a classic route to files outside the target directory and to decompression bombs.
- **Risk:** a legitimate archive could trip a limit; the limits are parameters of `extract_zip`.
- **Revisit when:** a source ships another container (tar, 7z, RAR).

## T12 — The tool fills three manifest fields, nothing else
- **Decision:** `ingest download` writes `acquisition.download_date` (on the first download only) and `acquisition.archive_sha256`; `ingest run` writes `acquisition.sha256_manifest`. The edit is a line-based text patch that keeps comments and layout, only fills fields that are still null, treats a different existing value as an integrity alarm (error, no overwrite), treats YAML block values as already set, and re-validates the patched text before writing. Every other manifest field is edited by hand, guided by the reconciliation table.
- **Evidence:** manifests are curated, commented documents; a first version of the patcher corrupted a multi-line YAML value in a test, and the re-validation refused to write it.
- **Reason:** re-serialising YAML would destroy comments; silently overwriting a recorded hash would hide tampering.
- **Risk:** the patch depends on the two-space layout of the template.
- **Revisit when:** a manifest needs a structure the patcher cannot handle.

## T13 — Grouping quality is measured and reported, not assumed
- **Decision:** each ingest report states whether the archive carries an identifiable group key and how good it is: `explicit` (`pcb-ind`: production batch and board side from the file name), `derived` (`pcb-defect`: first field of the original scan name, supported by image similarity) or `none` (`dspcbsd-plus`). The group-aware split A1 uses the key where it exists and similarity clusters (M3) where it does not, and every report says which.
- **Evidence:** [m2-ingest-report.md](../reports/m2-ingest-report.md): PCB-IND has 685 batches and 1,069 (batch, side) groups, and 125 batches occur in two splits; PCB-Defect has 22 design families over 230 images, and the most similar other image shares the family for 69% of the images against 5% by chance; DsPCBSD+ file-name families do not predict similarity (consecutive numbers are as different as random pairs).
- **Reason:** a group key claimed without evidence would hide exactly the leakage this project measures.
- **Risk:** a derived key is a hypothesis; a wrong key gives false safety.
- **Revisit when:** M3 produces similarity clusters for `dspcbsd-plus`, or an upstream author documents the key.

## T14 — Line length
- **Decision:** `ruff format` keeps code at 100 columns; rule E501 (line too long) is ignored.
- **Evidence:** URLs, hashes and message strings exceed the limit without being wrong.
- **Reason:** breaking a string only to satisfy a linter makes diffs and searches worse.
- **Risk:** none notable.
- **Revisit when:** a style guide is adopted.

## T15 — The audit never removes anything
- **Decision:** M3 detects, groups, measures, reports and prepares review. No image is deleted, excluded or re-labelled; every candidate pair carries `decision = review`, and the category is a suggestion, not a verdict.
- **Evidence:** [M3_PROTOCOL](M3_PROTOCOL.md) section 2; SPEC 6.4 allows automatic decisions only for exact duplicates, and there are none (0 identical SHA-256 inside or across the sources).
- **Reason:** a visual similarity group is not proof of the same physical board; what to do with a group (keep one, keep all in one split, not a duplicate) is a later, human decision that feeds release assembly (M5).
- **Risk:** the review queue can wait for a long time; until it is reviewed the thresholds rest on noisy group labels only.
- **Revisit when:** the maintainer reviews the queue, or M5 assembles the first release.

## T16 — Perceptual hash in house
- **Decision:** the 64-bit pHash (32x32 grayscale, 2-D DCT, 8x8 low-frequency block against its median) is computed with NumPy and Pillow (`openinspect.dedup.hashing`, version `phash-v1`), instead of the `imagehash` package planned in [DEPENDENCIES](DEPENDENCIES.md).
- **Evidence:** the definition is about twenty lines; `imagehash` would add a dependency (and SciPy) for one function.
- **Reason:** fewer dependencies; the version string is part of the hash store, so a change of definition cannot mix with old values.
- **Risk:** values can differ in detail from `imagehash`'s (resampling filter), so distances are not directly comparable with papers that used it.
- **Revisit when:** a comparison with published pHash distances is needed.

## T17 — torch from the CPU-only index, as an optional extra
- **Decision:** `torch` and `transformers` form the optional extra `embeddings`; `torch` comes from the official CPU-only index (`pyproject.toml`, `[tool.uv.sources]`). CI does not install the extra: tests use a stub embedder, and mypy ignores the missing imports.
- **Evidence:** the CUDA wheels are about 2 GB and the machine's GPU has 4 GB of VRAM; DINOv2-small on the CPU (i5-11300H) embedded 15,158 images at 10.2 images/s in the model (1,548 s in all).
- **Reason:** one backend on every platform (`cpu-fp32`, part of the cache key), a small CI, and results that do not depend on a GPU driver.
- **Risk:** larger models (DINOv2-base, the robustness check) are slower on the CPU.
- **Revisit when:** a GPU run is needed; it gets its own backend name and cache directory.

## T18 — Exact search with NumPy, no approximate index
- **Decision:** cosine similarity on L2-normalised vectors in row blocks of 1,024 (`openinspect.dedup.similarity`); no FAISS.
- **Evidence:** 15,278 vectors of 384 numbers: the global top-10 takes about 4 s and all pairs of a source a few seconds.
- **Reason:** an approximate index would put search error into the calibration and the leakage counts (protocol section 4).
- **Risk:** memory grows with the square of a block, not of the data; beyond about a million images a real index is needed.
- **Revisit when:** the pool grows by an order of magnitude.

## T19 — Embedding cache and pinned weights
- **Decision:** one `.npy` file per image under `<data>/embeddings/<model>@<revision>/<preprocessing>/<backend>/`, keyed by the image SHA-256; the model is pinned by Hub revision and the SHA-256 of its safetensors file (`configs/dedup.yaml`), checked before loading.
- **Evidence:** a changed image, model, revision, preprocessing or backend changes the numbers; each of them is part of the key, so a stale vector cannot be read.
- **Reason:** an interrupted run resumes where it stopped, and the analysis needs no model at all.
- **Risk:** reading 15,278 small files takes about 90 s on Windows; a packed matrix would be faster.
- **Revisit when:** the read time matters, or a second model is added (DINOv2-base has its own directory).

## T20 — What M3 puts in git
- **Decision:** tracked: `artifacts/m3/audit.json` (every number of the reports), `leakage-groups.parquet`, `duplicate-pairs.parquet`, `review-candidates.csv`, the reports in `reports/m3/` and their SVG figures. Not tracked: `nearest-neighbors.parquet` (about 1.4 MB, regenerable, listed with its SHA-256 in `audit.json`), the embedding and synthetic caches, the run records and logs, and the HTML review pack, which embeds thumbnails of dataset images (all under `<data>/m3/`).
- **Evidence:** the tracked tables are each under 0.3 MB and hold file names, similarities and group memberships, no pixels.
- **Reason:** a reader can check every reported number against a tracked table; nothing of the datasets' pixels enters the repository (licence and size).
- **Risk:** a different pyarrow version writes different Parquet bytes; the digests in `audit.json` then change on a rerun although the content does not.
- **Revisit when:** a table passes 1 MB, or a release needs the neighbour table.

## T21 — Protocol first, amendments apart
- **Decision:** the M3 rules were committed before any number was computed; the file stays byte-identical (a test checks its SHA-256), and every later correction or clarification goes to [M3_PROTOCOL_AMENDMENT](M3_PROTOCOL_AMENDMENT.md) with its time relative to the first run.
- **Evidence:** `8572b7e` (protocol) precedes `d844365` (rule code) and the first end-to-end run (2026-09-30 23:12).
- **Reason:** a reader can tell which choices could have been influenced by the results.
- **Risk:** a real error in the protocol would stay in the frozen file; the amendment file must be read with it.
- **Revisit when:** the next audit (a new source or model) starts; it gets its own protocol.

## T22 — A branch for the resumed milestone
- **Decision:** M3 was finished on `m3-resume` (a recovery snapshot of the uncommitted work first) and merged into `main` by fast-forward, without a pull request. This departs from T7 (work on `main`) for one milestone, at the maintainer's request.
- **Evidence:** the previous session stopped with uncommitted work; a branch made it safe to push that work before it was finished.
- **Reason:** nothing unfinished reached `main`, whose CI must stay green.
- **Risk:** none beyond T7's (no review gate).
- **Revisit when:** a second contributor joins (then pull requests).

## T23 — Run records for the performance report
- **Decision:** `dedup features` and `dedup synthetic` append one JSON line per run to `<data>/m3/runs/<stage>.jsonl`; the performance report takes, per stage, the run that embedded the most images, next to the measured stages of the analysis.
- **Evidence:** a rerun reads the caches and embeds nothing, so its time would hide the real cost of the model.
- **Reason:** the report shows what embedding actually costs on this machine.
- **Risk:** the two runs made before the record existed were transcribed from their console logs (amendment N5); their values are rounded as printed.
- **Revisit when:** the cache is rebuilt, which writes a complete record.
