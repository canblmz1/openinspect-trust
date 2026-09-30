# Licence acceptance checklist

One completed checklist per source. **Admission gates (G1–G6, G9)** decide whether a source may be `accepted`. **Ingest gates (G7, G8)** are verified in Milestone 2, when the data is downloaded; a failure there returns the source to `pending` or `rejected`. All three accepted sources passed both on 2026-09-30. Any failed gate ends in `status: rejected` (DO NOT USE) with the reason recorded in the manifest.

## Hard rules

1. **Unclear means no.** A missing, ambiguous or conflicting licence → DO NOT USE.
2. **Read the licence from the data record** (repository record first, DOI registry second). Papers and READMEs are cross-checks, never the primary source. Record the retrieval date.
3. **Conflicts:** when record, README, paper or `LICENSE` file disagree about the *data*, the most restrictive reading applies until the rights-holder clarifies in writing. Keep the email.
4. **Allowlist for v0.1** (`configs/licences.yaml`): `CC0-1.0`, `CC-BY-4.0`. Anything else needs an explicit written decision in the manifest and a change of the allowlist.
5. **Blocked:** any NC, ND or SA term; "research only", "academic use only", "contact the author"; custom licences; no licence.
6. **Downloads.** Metadata and evidence snapshots may be downloaded at any time. Dataset archives are downloaded only in the ingest milestone and only for `accepted` sources.

## Gates

| gate | check | pass criterion | on fail |
|---|---|---|---|
| **G1 Identity and provenance** | Official record URL, DOI, paper, creators and affiliations recorded. The uploader is the creator (a record author appears in the paper). Record version pinned. | `identity.*` filled, `is_original_upload: true` | mirror or aggregator with no verifiable upstream → reject |
| **G2 Licence on the record** | Licence read from the repository record; exact SPDX id and URL copied; date noted. | explicit licence on the record | none stated → reject |
| **G3 Cross-check** | Compare record, DOI registry, README, paper and `LICENSE` file. List every disagreement in `licence.conflicts`. | no conflict, or a conflict that does not touch data rights (e.g. the licence of the article text) and is documented | data-rights conflict unresolved → reject |
| **G4 Allowlist** | SPDX id is on the allowlist (rule 4). | on the allowlist | reject |
| **G5 Four rights questions** | Redistribution, derivative works (format conversion, crop/tile, relabel, re-encode), commercial use, attribution wording. All four answered. | answers recorded; credit line written | unanswered → stay `pending` |
| **G6 Independence** | Authors, institutions, production line or lab, and device are disjoint from the other accepted sources; no shared base dataset. | documented in `provenance_risks.independence_notes` | cannot count as an independent source |
| **G7 Quality intake** *(ingest)* | Class distribution, sample count, annotation format, resolution, pixel pitch, environment, known duplicates, known weaknesses, official splits: first from record and paper, then re-computed from the archive and reconciled. | every `content.*` value filled or an explicit `null` with a note; discrepancies written down | no silent gaps |
| **G8 Reproducible download** *(ingest)* | Scriptable URL, record checksum verified, our SHA-256 computed, every image decodes, size fits the disk budget, no third-party marks in the images. | checksums match, 0 decode failures | stop and investigate |
| **G9 Evidence and decision** | Records archived under `manifests/evidence/<slug>/` and hashed; `decision.*` filled; `status` set. | all present, `openinspect source validate` passes | stay `pending` |

**Two tiers.** `accepted` = admitted for download and internal use. **Public release** also needs `redistribution` and `derivative_work` to be `allowed`; an `unclear` or `not_allowed` answer blocks it (`openinspect source validate --release public`). With the v0.1 allowlist (CC0, CC BY 4.0) both are `allowed` by the licence itself.

## Licence-laundering red flags

- A permissive tag on a Hub, Kaggle or Roboflow re-upload of a dataset that has a named original.
- A class list, image count or file names identical to a known restricted dataset.
- No paper, no institution, no description of how the images were acquired.
- The licence is stated only on the mirror, not on the original record.
- "Free for research" wording anywhere near a permissive label.

From M3 the cross-source near-duplicate audit doubles as a provenance test: a source that turns out to contain another source's images fails G1 and G6 retroactively.

## Status (2026-09-30)

✅ pass · ⚠️ pass with a caveat · ☐ pending · ❌ failed · — not evaluated

| gate | `dspcbsd-plus` | `pcb-defect` | `pcb-ind` | `deeppcb` |
|---|---|---|---|---|
| G1 | ✅ | ✅ | ✅ | ⚠️ paper authors unverified |
| G2 | ✅ CC BY 4.0 | ✅ CC BY 4.0 | ✅ CC BY 4.0 | ⚠️ MIT file vs README |
| G3 | ✅ no conflict | ✅ no conflict | ⚠️ article CC BY-NC-ND, dataset CC BY 4.0 (scoped, documented) | ❌ data-rights conflict |
| G4 | ✅ | ✅ | ✅ | — |
| G5 | ✅ | ✅ | ✅ | — |
| G6 | ⚠️ same modality as `pcb-ind` | ✅ lab vs factory | ⚠️ same modality as `dspcbsd-plus` | — |
| G7 | ✅ reconciled (M2) | ✅ reconciled (M2) | ✅ reconciled (M2) | — |
| G8 | ✅ size, MD5, SHA-256, 0 undecodable | ✅ size, SHA-256, 0 undecodable | ✅ size, MD5, SHA-256, 0 undecodable | — |
| G9 | ✅ evidence hashed | ✅ evidence hashed | ✅ evidence hashed | ✅ rejection evidenced |
| **status** | **accepted** | **accepted** | **accepted** | **rejected** |

## Ingest results (M2, 2026-09-30)

What gates G7 and G8 found when the archives were downloaded and read ([reports/m2-ingest-report.md](../reports/m2-ingest-report.md), [manifests/ingest/](../manifests/ingest/)):

| check | `dspcbsd-plus` | `pcb-defect` | `pcb-ind` |
|---|---|---|---|
| archive size equals the record | yes (128,541,608 B) | yes (158,048,862 B) | yes (101,336,845 B) |
| record checksum | MD5 equal | SHA-256 equal | MD5 equal |
| zip CRC-32 of every member | pass | pass | pass |
| images decoded | 10,259 of 10,259 | 230 of 230 | 4,789 of 4,789 |
| exact duplicates (SHA-256) inside the source | 0 | 0 | 0 |
| images / boxes equal the manifest | 10,259 / 20,276 | 230 / 1,704 | 4,789 / 5,932 |
| the archive's own licence statement | COCO `licenses` entry is empty: no statement, the record stands | COCO file says CC BY 4.0: consistent | README defers to the Zenodo record: consistent |
| third-party marks (12 seeded-random images per source looked at) | none seen | none seen | none seen |

Across the three sources no SHA-256 occurs twice. The manifests were corrected where an archive differed from its record or paper: DsPCBSD+ has 111 images of 108×108 (not all 226×226) and ships no VOC files; PCB-Defect images measure 1540×1285 to 5971×5236 (the record says 800×600 to 6000×4000) and its class strings are lower-case with underscores; PCB-IND per-class counts were measured, and its `classes.json` agrees with the Zenodo description, so the GitHub README class list is stale. Pixel pitch cannot be derived: no image carries EXIF or a DPI value. The look at third-party marks is a sample, not an exhaustive check; the label audit (M4) looks at many more images.

## Decision record (the `decision` block of a manifest)

```yaml
decision:
  status: accepted            # or rejected
  decided_by: project-maintainer
  decided_on: 2026-09-30
  evidence: [manifests/evidence/<slug>/...]
  reason: "..."
```

## Release checklist (before any public release of a compiled dataset)

- [ ] R1 `ATTRIBUTION.md` lists every source with creators, title, record and DOI, licence and URL.
- [ ] R2 The change statement is present and accurate.
- [ ] R3 The release licence is CC BY 4.0 and adds no restrictions.
- [ ] R4 Every source manifest is `accepted`, its evidence is archived, and `validate --release public` passes.
- [ ] R5 No article text or figures from papers with a stricter licence were copied.
- [ ] R6 The EVREN dataset description carries the same attribution and licence.
