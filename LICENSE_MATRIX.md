# Licence matrix

Last verified: 2026-09-30 · Gate policy: [docs/LICENCE_CHECKLIST.md](docs/LICENCE_CHECKLIST.md) · Facts: [manifests/sources/](manifests/sources/) · Evidence: [manifests/evidence/](manifests/evidence/), hashed in [SHA256SUMS.txt](manifests/evidence/SHA256SUMS.txt)

**Rule of this project: an unclear licence means DO NOT USE.** "Unclear" includes: no licence on the data record; conflicting statements (the most restrictive reading applies until the rights-holder clarifies in writing); NC, ND or SA terms; "research only" wording; a re-upload whose uploader cannot be shown to hold the rights.

Two tiers (decision T4 in [docs/DECISIONS.md](docs/DECISIONS.md)):

- **accepted**: admitted for download and internal research use.
- **public release**: additionally needs `redistribution` and `derivative_work` to be `allowed`. An unclear answer blocks it.

This file summarises the manifests; the manifests are the source of truth.

## A. Accepted

Each licence was read from the repository record, confirmed by the DOI registry (DataCite), and the paper's own licence was read from Crossref. The records are archived and hashed. The archives were downloaded and verified in Milestone 2 (2026-09-30): size and checksum equal the records, and no licence statement inside an archive contradicts them.

| slug | licence | record (pinned) | archive listed by the record | repository record says | DataCite says | paper (Crossref) says |
|---|---|---|---|---|---|---|
| `dspcbsd-plus` | CC-BY-4.0 | [figshare v1](https://doi.org/10.6084/m9.figshare.24970329.v1) | `DsPCBSD+.zip`, 128,541,608 B, MD5 `508334b6…5a80a81` | CC BY 4.0 | CC BY 4.0 | article CC BY 4.0 |
| `pcb-ind` | CC-BY-4.0 | [Zenodo v4](https://doi.org/10.5281/zenodo.19723114) | `PCB-IND_v4.zip`, 101,336,845 B, MD5 `1325f8df…b31ec5` | cc-by-4.0, open access | CC BY 4.0 | **article CC BY-NC-ND 4.0** (not the dataset) |
| `pcb-defect` | CC-BY-4.0 | [Mendeley Data v1](https://doi.org/10.17632/vdj74sngvn.1) | `PCB_Defect.zip`, 158,048,862 B, SHA-256 `a5fb17e7…cb5f2a` | CC BY 4.0 | CC BY 4.0 and open access | article CC BY 4.0 |

For all three: redistribution, adaptation and commercial use are allowed by CC BY 4.0, on condition that the creators are credited, the licence is linked, changes are indicated and no endorsement is suggested. "Adaptation" covers what this project does: format conversion, cropping or tiling, relabelling, removing items.

## B. Excluded — DO NOT USE

| dataset | why | how we know | reopen only if |
|---|---|---|---|
| DeepPCB (tangsanli5201), manifest [`deeppcb`](manifests/sources/deeppcb.yaml) | The repository `LICENSE` file is MIT (2018) while the README says the dataset may only be used for research purposes. The two disagree and neither gives reliable clarity on redistribution of the dataset. The README also says part of the defects in the tested images were added manually. | archived README, LICENSE and GitHub repository record | the authors clarify in writing that redistribution and derivative works are allowed |
| PKU-Market-PCB / HRIPCB (Huang & Wei) | The PCB-IND paper describes it as 1,386 *synthesized* PCB defect images. No open licence was located during screening. | earlier screening note, **not re-verified in the second pass** | a primary source states an open licence |
| Hub, Kaggle or Roboflow re-uploads with permissive tags, e.g. Hugging Face `RobotHuman/PCB_defect` (tag MIT) | Its card describes 1,386 images with defects inserted in Photoshop and cites arXiv:1901.08204, so it looks like a re-upload of the Huang & Wei data. A Hub tag does not show that the uploader holds the rights. | Hub search result and card summary | never as a source; use the upstream record |
| "Mixed PCB Defect Dataset" (Mendeley fj4krvmrr5) | Labelled CC BY 4.0, but the earlier screening note found unclear image provenance and a class list identical to PKU-Market-PCB: possible licence laundering. | earlier screening note, **not re-verified** | the uploader documents original image acquisition |
| Hugging Face `Mobiusi/…` and `TerLiphi/PCB-Solder-Joint-Defect-Detection-Dataset` | Tagged CC BY-NC-SA 4.0: NC and SA are outside the allowlist. Different task (solder joints). | Hub search result | never for v0.1 |
| Hugging Face `keremberke/pcb-defect-segmentation` | Roboflow export with no licence tag; solder-joint classes on assembled boards; segmentation. | Hub search result | never for v0.1 |
| GC10-DET, CODEBRIM, dacl10k, dacl1k, S2DS (other domains) | Excluded during the earlier screening for licence or annotation-type reasons. **No claim about their exact terms is made here.** | earlier screening notes, not re-verified | the project changes domain |

## C. Licence traps found while screening

1. **`LICENSE` file vs README** (DeepPCB): the file says MIT, the README restricts use to research.
2. **Article licence vs dataset licence** (PCB-IND): the paper's text and figures are CC BY-NC-ND while its dataset is CC BY 4.0. Take the dataset licence from the data record, and do not copy article text or figures.
3. **Permissive tags on re-uploads**: a Hub, Kaggle or Roboflow tag says nothing about the uploader's rights.
4. **A "CC BY" label does not prove ownership** of the images (Mixed PCB). Check that the uploader is the creator and that the paper describes original acquisition.
5. **Documentation drift**: the PCB-IND GitHub README and the Zenodo v4 description list different classes. Pin the record version and read labels from the files.
6. **Registry generic caveats**: Mendeley's licence text warns that third-party content inside a dataset may need further permission. Re-check images for third-party marks at ingest (M2: a seeded sample of 12 images per source showed none; the check is not exhaustive).

## D. Obligations when releasing "OpenInspect-Trust v0.1" (CC BY 4.0 inputs)

- Ship an `ATTRIBUTION.md` with, for every source: creators, title, repository and DOI, licence and URL, and a change statement. The `attribution_text` in each manifest is the starting point; use each record's own "Cite as" wording.
- Change statement (draft, finalise in M6): images cropped or tiled where noted, re-indexed with new IDs, labels mapped to a common taxonomy, some items removed as duplicates or unmappable, boxes converted to YOLO format, no pixel-level enhancement.
- Release the compilation under CC BY 4.0 and add no restrictions (no NC, no click-through).
- Do not imply endorsement by the original creators.
- Publishing on EVREN as a public dataset counts as redistribution: same obligations; read EVREN's terms for third-party uploads first.
- If any source is replaced by an NC or SA one, the release licence changes: redo this matrix first.

Software and model-weight licences (Ultralytics is AGPL-3.0): [docs/DEPENDENCIES.md](docs/DEPENDENCIES.md).
