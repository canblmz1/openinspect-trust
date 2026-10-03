# Data availability

**Source data.** The three source datasets are public and licensed CC BY 4.0 by their publishers. They are not redistributed in modified form beyond what the release documents:

- DsPCBSD+: doi:10.6084/m9.figshare.24970329.v1 (Lv et al., *Sci. Data* 11:811, 2024).
- PCB-IND: doi:10.5281/zenodo.19723114 (Yan et al., *Sci. Data* 13:1356, 2026).
- PCB-Defect: doi:10.17632/vdj74sngvn.1 (Rashid et al., *Data in Brief* 64:112296, 2025).

**Release v0.1.** The repository contains the manifest: per image, the source item, the SHA-256 of the source and released file, crop coordinates and labels. Anyone holding the source archives (SHA-256 recorded) can rebuild the identical release with the published command. CC BY requires that changes are indicated; the manifest records every crop, exclusion and class mapping.

**Splits and designs.** All split, design and role manifests are in `manifests/`.

**Model weights.** Not redistributed. Reasons:
- they are not needed to check the reported numbers, which are recomputable from the released per-image predictions;
- they were produced on a third-party platform under that platform's terms;
- Ultralytics YOLO11 is AGPL-3.0, so redistributed weights would carry obligations the authors have not assessed.

SHA-256 hashes of every checkpoint used are published, so any copy shared later can be verified.

**Per-image predictions and AI review labels.** Available as a data supplement on request, and intended for deposit with the preprint. They contain no personal data.

**Platform identifiers.** Job and model-version identifiers of the training platform are kept private. Runs are referenced by aliases.
