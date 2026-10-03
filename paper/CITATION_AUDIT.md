# Citation audit (3 October 2026)

**Tools.** SciSpace and Scite were **not available** in this session (no connector exists). Each reference was verified with a general web search against primary sources: publisher landing pages, DOI/Crossref records, arXiv abstract pages, PubMed/PMC, CVF open access, and the dataset repositories' records (the latter archived in the repository under `manifests/evidence/` with SHA-256 hashes). **No citation-context analysis (supports / contradicts) was performed.** "What it shows" summarises the abstract or landing page; full texts were not re-read for this audit except where stated.

| # | reference | title, authors, year, venue verified | DOI / ID verified | what it actually shows (as used in the paper) | status |
|---|---|---|---|---|---|
| 1 | Barz & Denzler | "Do We Train on Test Data? Purging CIFAR of Near-Duplicates"; B. Barz, J. Denzler; *J. Imaging* 6(6):41, 2020 | 10.3390/jimaging6060041; arXiv:1902.00423; PMC8321059 | 3.3% / 10% of CIFAR-10/100 test images have training duplicates; releases the duplicate-free ciFAIR test sets | **kept** |
| 2 | Laroca et al. | "Do We Train on Test Data? The Impact of Near-Duplicates on License Plate Recognition"; R. Laroca, V. Estevam, A. S. Britto Jr., R. Minetto, D. Menotti; IJCNN 2023 | 10.1109/IJCNN54540.2023.10191584; arXiv:2304.04653 | near-duplicates (same plate) across splits; under duplicate-free "fair" splits error rates more than double and model rankings change | **kept** |
| 3 | Tampu et al. | "Inflation of test accuracy due to data leakage in deep learning-based classification of OCT images"; I. E. Tampu, A. Eklund, N. Haj-Hosseini; *Sci. Data* 9:580, 2022 | 10.1038/s41597-022-01618-6 | per-image vs per-subject splits; MCC inflated by 0.07–0.43 (accuracy 5–30%) | **kept** |
| 4 | Figueiredo & Mendes | "Analyzing Information Leakage on Video Object Detection Datasets by Splitting Images Into Clusters With High Spatiotemporal Correlation"; R. B. D. Figueiredo, H. A. Mendes; *IEEE Access*, 2024 | 10.1109/ACCESS.2024.3383047 (IEEE Xplore 10485397) | random splits of correlated video frames leak information; cluster-based splitting (CLIP features, t-SNE), tested with YOLOv8 | **added** (closest detection-domain group-leakage work) |
| 5 | DataSAIL | "Data splitting to avoid information leakage with DataSAIL"; R. Joeres, D. B. Blumenthal, O. V. Kalinina; *Nat. Commun.* 16:3337, 2025 | 10.1038/s41467-025-58606-8 | leakage-reduced splitting as combinatorial optimisation, mainly for biomedical data | **kept** |
| 6 | Babu et al. (automotive) | "Improving Image Data Leakage Detection in Automotive Software"; M. A. A. Babu, S. K. Pandey, D. Durisic, A. C. Koppisetty, M. Staron; arXiv 2024 | arXiv:2410.23312 | leaks test images into training incrementally and retrains a YOLOv7 detector evaluated on the same test set; uses pHash-based detection | **kept** as arXiv; peer-reviewed venue **not verified**, so cited as arXiv only |
| 7 | AeBAD | "Industrial anomaly detection with domain shift: A real-world dataset and masked multi-scale reconstruction"; Z. Zhang, Z. Zhao, X. Zhang, C. Sun, X. Chen; *Computers in Industry* 151:103990, 2023 | arXiv:2304.02216; ScienceDirect S0166361523001409 | aero-engine blade anomaly dataset with domain shift (illumination, view) between training and test | **kept** |
| 8 | Robust AD | "Robust AD: A Real World Benchmark Dataset for Robustness in Industrial Anomaly Detection"; L. Pemula, D. Zhang, O. Dabeer; CVPR Workshops (VAND) 2025, pp. 4086–4096 | CVF open access page | anomaly-detection benchmark with controlled real distribution shifts | **kept** (venue corrected to CVPR *Workshops*) |
| 9 | Sun et al. | "Revisiting Unreasonable Effectiveness of Data in Deep Learning Era"; C. Sun, A. Shrivastava, S. Singh, A. Gupta; ICCV 2017 | arXiv:1707.02968; CVF open access | removing near-duplicates of JFT-300M from COCO minival (1,648 images) had minimal impact on results | **kept** |
| 10 | UniPCB | "UniPCB: A Unified Vision-Language Benchmark for Open-Ended PCB Quality Inspection"; F. Sun, X. Jiang, J. Wu, H. Zhang, F. Zheng, J. Yang; arXiv 2026 | arXiv:2601.19222 | vision-language PCB benchmark curated from public data across imaging modalities | **kept** (context only; peer-reviewed venue not verified) |
| 11 | DsPCBSD+ | "A dataset for deep learning based detection of printed circuit board surface defect"; S. Lv et al.; *Sci. Data* 11:811, 2024 | 10.1038/s41597-024-03656-8; dataset 10.6084/m9.figshare.24970329.v1; PMC11263390 | 10,259 images, 20,276 boxes, 9 classes; images from industrial PCB production | **kept** |
| 12 | PCB-IND | "Industrial Printed Circuit Board Surface Defect Dataset for Object Detection"; H. Yan et al.; *Sci. Data* 13:1356, 2026 | 10.1038/s41597-026-07684-4; dataset 10.5281/zenodo.19723114 | 4,789 images from an inline industrial AOI system, 8 classes | **kept**; full author list (9 authors) taken from the Crossref record archived with SHA-256 in `manifests/evidence/pcb-ind/` |
| 13 | PCB-Defect | "PCB-Defect: An annotated dataset for surface defect detection in printed circuit boards"; A. J. Rashid, M. A. Ullah, A. Isfara, N. Ahmed, M. M. Mian, M. M. Shalehin; *Data in Brief* 64:112296, 2025 | 10.1016/j.dib.2025.112296; dataset 10.17632/vdj74sngvn.1 | 230 high-resolution images of laboratory-fabricated single-layer FR4 boards, 1,704 boxes, 6 classes | **kept**; earlier "flatbed scan / DIY board" wording **removed** because the source does not say this |
| 14 | DINOv2 | "DINOv2: Learning Robust Visual Features without Supervision"; M. Oquab et al.; TMLR 01/2024 | arXiv:2304.07193 | self-supervised visual features used for similarity | **kept** |
| 15 | Ultralytics YOLO11 | G. Jocher, J. Qiu; software v11.0.0, 2024 (official CITATION.cff) | github.com/ultralytics/ultralytics | detector and evaluator software | **kept** (software citation; AGPL-3.0 noted) |

## Removed or not added

| candidate | reason |
|---|---|
| "PCB cross-domain / domain-adaptation detection work" | No specific paper was verified that matches the claim in the time available. Not cited; no claim depends on it. |
| "D-LeDe … multiple automotive datasets" (SN Computer Science 2026) and "Data Leakage in Automotive Perception: Practitioners' Insights" (arXiv:2604.06899) | Seen in search results, but authors and content were not verified. Not cited. |
| Any "first" or novelty claim | Not supported by an exhaustive search. The paper says "we did not identify prior work combining these elements". |

## Open items before submission

- Re-check whether [6] and [10] have appeared at a peer-reviewed venue.
- If Scite becomes available, run a citation-context check on [1]–[5].
