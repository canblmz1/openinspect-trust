<!-- Generated from manuscript.md (single source of truth); do not edit separately. -->

## 2. Related Work

**Near-duplicate contamination.** Barz and Denzler found that 3.3% (CIFAR-10) and 10% (CIFAR-100) of test images have duplicates in the training set and released duplicate-free test sets [1]. Laroca et al. showed that near-duplicates of the same licence plate across splits bias licence-plate recognition: error rates more than doubled under duplicate-free ("fair") splits, and model rankings changed [2]. Not every audit finds large effects: Sun et al. removed near-duplicates of their pre-training data from COCO minival and reported minimal impact on detection results [9].

**Group and subject-level leakage.** Tampu et al. showed that slice-level instead of subject-level splitting of OCT volumes inflates classification performance (MCC +0.07 to +0.43; accuracy +5 to +30%) [3]. Figueiredo and Mendes showed that randomly splitting highly correlated frames of video-derived object-detection datasets causes information leakage, and proposed cluster-based splitting evaluated with YOLOv8 [4]. Joeres et al. formulate leakage-reduced splitting as an optimisation problem (DataSAIL) [5]. Our setting is the detection analogue of subject-level leakage. The "subject" is a machine-detected group rather than a known patient or video ID.

**Controlled leakage experiments.** Babu et al. deliberately moved increasing fractions of test images into the training set of an automotive object detector and evaluated on the same test set [6]. Their manipulation injects copies of test images. Ours swaps naturally occurring group-mates for profile-matched replacements and separates exposed from unexposed images within one test set.

**Source and domain shift in industrial inspection.** AeBAD [7] and Robust AD [8] document large performance drops of anomaly detectors under acquisition changes (illumination, viewpoint, background). UniPCB aggregates public PCB imagery from multiple modalities into a vision-language benchmark [10]. Our source-held-out arm reports the same kind of shift for supervised PCB defect detection. It also shows that source identity is trivially encoded in image metadata.

**Position of this work.** Leakage, near-duplicate contamination, group-aware splitting and domain shift are all known. This paper is a controlled case study: it measures how much group exposure inflates a specific industrial detection benchmark, how selective that inflation is, and how it compares with source shift.

*Literature-search limitation.* SciSpace and Scite were not available. References were verified against publisher pages, DOIs, arXiv and PubMed/PMC (`paper/CITATION_AUDIT.md`), but no systematic citation-context analysis was done.

