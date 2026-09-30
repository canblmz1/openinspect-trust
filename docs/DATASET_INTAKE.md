# Dataset intake format

What must be known about a source before it can enter the project, and where to find each fact. The format is [`manifests/sources/_template.yaml`](../manifests/sources/_template.yaml); the acceptance gates are in [LICENCE_CHECKLIST](LICENCE_CHECKLIST.md); `openinspect source validate` enforces the rules.

## Three artefacts per source

1. `manifests/sources/<slug>.yaml`: the source manifest (facts and decision).
2. `manifests/evidence/<slug>/`: saved snapshots of the repository record, the DOI-registry record and the paper's registry record, hashed in `manifests/evidence/SHA256SUMS.txt`.
3. The gate table in [LICENCE_CHECKLIST](LICENCE_CHECKLIST.md).

Never fill a value from memory or from a mirror. Unknown → `null` plus a note.

## Brief §10 fields → manifest keys

| brief field | manifest key |
|---|---|
| dataset_name | `dataset_name` |
| official_url | `identity.official_url` |
| doi | `identity.doi` |
| license | `licence.spdx` (+ `licence_url`, `stated_in`, `conflicts`) |
| redistribution | `licence.redistribution` |
| derivative_work | `licence.derivative_work` |
| commercial_use | `licence.commercial_use` |
| citation | `citation.citation_text` |
| download_method | `acquisition.download_method` |
| version | `identity.version` |
| download_date | `acquisition.download_date` |
| sha256_manifest | `acquisition.sha256_manifest` |

Added because the brief's own rules need them: `identity.is_original_upload` (licence-laundering check), `licence.attribution_*` (release obligations), `content.source_group_key` (grouped-leakage test, brief §36), `content.original_classes` (the taxonomy is derived from real labels, brief §18), `provenance_risks.*` (brief §9 quality items), `decision.*` (who decided, on what evidence).

## Where to read each fact

| fact | figshare | Zenodo | Mendeley Data |
|---|---|---|---|
| licence | API `license.name` and `license.url` | API `metadata.license.id` | public API `data_licence` |
| files, size, checksum | API `files[]`: `size`, `computed_md5`, `download_url` | API `files[]`: `key`, `size`, `checksum`, `links.self` | public API `files[]`: `content_details.sha256_hash`, `size`, `download_url` |
| version, date | API `version`, `published_date` | API `metadata.publication_date` | API `version`, `publish_date` |
| creators | API `authors` (may list only the lead) | API `metadata.creators` (may list only the lead) | API `contributors` |
| independent confirmation | DataCite `rightsList` | DataCite `rightsList` | DataCite `rightsList` |

Every registered DOI has a DataCite record (`https://api.datacite.org/dois/<doi>`); a paper's licence is in its Crossref record (`https://api.crossref.org/works/<doi>`). Checksums published by repositories are MD5 (figshare, Zenodo) or SHA-256 (Mendeley). They prove the download is intact. The project's own hash is SHA-256, computed by `ingest`.

## Procedure

1. **Identify.** Open the record, fill `identity.*`. Confirm that a record author appears in the paper.
2. **Read the licence** on the record; fill `licence.spdx`, `licence_url`, `stated_in`. Set `verified_on`.
3. **Cross-check** the DOI registry, README, paper and `LICENSE` file; write every disagreement into `licence.conflicts`.
4. **Answer the four rights questions** (redistribution, derivative_work, commercial_use, attribution). Write the credit line.
5. **Archive the evidence.** Save the snapshots under `manifests/evidence/<slug>/`, then regenerate the hash list:

   ```bash
   curl.exe -sS -L -o manifests/evidence/<slug>/datacite_<doi with / as _>.json https://api.datacite.org/dois/<doi>
   ```

   ```bash
   python scripts/hash_evidence.py
   ```

   Copy each file's hash from `SHA256SUMS.txt` into the manifest's `licence.evidence`.
6. **Fill the quality block** (`content.*`, `provenance_risks.*`) from the paper and record. These are claims until step 8.
7. **Judge independence** (`independence_notes`): producer, device, line or lab, shared origin.
8. **Reconcile at ingest (M2).** After the download, recompute image count, class counts, sizes and split counts from the archive, compare with the manifest, and write discrepancies into `notes`.
9. **Decide.** Fill `decision.*` and set `status` to `accepted` or `rejected`, then run:

   ```bash
   uv run openinspect source validate
   ```

## Open items for the accepted sources (resolved at ingest, M2)

| slug | still open |
|---|---|
| `dspcbsd-plus` | how crops map to boards (`source_group_key`); colour vs grayscale; pixel pitch; the label strings in the files |
| `pcb-defect` | COCO category names; whether released images were cropped or resized (pixel pitch); third-party marks in images |
| `pcb-ind` | per-class counts; read `classes.json` (README and Zenodo class lists disagree); check that the first four filename characters encode the batch |

## Worked example: what the format caught in PCB-IND

- The paper is CC BY-NC-ND and the dataset CC BY 4.0 → `licence.conflicts` records that the dataset licence comes from the Zenodo record, confirmed by DataCite.
- README and Zenodo list different classes → `known_weaknesses` says `classes.json` is authoritative.
- The authors deduplicated only within a production batch → `known_duplicates` says cross-batch duplicates are unchecked, so our audit must not assume the set is clean.
