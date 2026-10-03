# Author checklist (before submitting)

No workshop has been chosen. Items marked **[venue]** depend on the call for papers.

## Content: done

- [x] Title free of "near-duplicate", "leakage detection", "first".
- [x] Abstract leads with the pre-specified primary endpoint and states the uncertainty, the mixed replication, the source-shift result and the absence of human validation. It is 239 words / 1,677 characters (within arXiv's 1,920-character limit).
- [x] D0, D1 and D2 are shown side by side in the main text (Table 1, Figure 3); no seed pair is omitted.
- [x] Test-sampling, training-seed and combined uncertainty are reported separately.
- [x] Placebo p-values are described as conditional on the trained models and not causal.
- [x] Exposure strata: it is disclosed that they were defined after five of the eight seed pairs had been evaluated.
- [x] "AI visual adjudication was performed …; independent human validation was not performed" appears in the abstract, Section 6.2, the limitations and the discussion.
- [x] Every reference verified (`paper/CITATION_AUDIT.md`); unverifiable ones removed.
- [x] Numbers cross-checked against the frozen CSVs (`reports/m7_final/PUBLICATION_CONSISTENCY_AUDIT.md`).
- [x] Hostile review done (`paper/FINAL_REVIEWER_2_AUDIT.md`).

## To do by the author

- [ ] Author name is set from the repository account ("Can", GitHub canblmz1). Add full name, affiliation and e-mail if desired (placeholders, not invented).
- [x] `paper/arxiv/main.tex` compiled with Tectonic 0.17.0 to `main.pdf` (14 pages); pages rendered and inspected (tables, figures, citations, bibliography).
- [ ] **[venue]** Apply the workshop template, page limit and anonymisation rules. `ANONYMIZED_MANUSCRIPT.md` and `paper/arxiv/main_anonymous.tex` remove the repository URL and the platform name.
- [ ] **[venue]** Check whether a non-archival workshop allows a simultaneous arXiv preprint.
- [ ] Decide whether to deposit the per-image predictions and AI review labels (for example on Zenodo) and add the DOI to the data-availability statement.
- [ ] Optional, strongly recommended: independent human review of the 90 prepared pairs (90 = 60 probe and 30 control pairs; blinded sheets and the A–G protocol exist). If done, report it as a separate, dated addition. Do not edit the AI results.
- [ ] Commit and tag the frozen state; replace the commit placeholder in `FINAL_FREEZE_MANIFEST.md`.
