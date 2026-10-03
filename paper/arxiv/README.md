# arXiv package

| file | content |
|---|---|
| `main.tex` | named version, generated from `../manuscript.md` by `../scripts/md_to_latex.py` |
| `main.pdf` | compiled named version: 14 pages, Tectonic 0.17.0 (XeTeX + BibTeX) |
| `main_anonymous.tex`, `main_anonymous.pdf` | double-blind version: repository URL and platform name removed; 14 pages |
| `references.bib` | 15 entries, each verified (see `../CITATION_AUDIT.md`) |
| `figures/` | three figures generated from the frozen CSVs by `../scripts/make_figures.py` |

**Build status.**
- Compiled with `tectonic -X compile main.tex`, with no LaTeX errors and no overfull boxes.
- Pages were rendered and inspected: title, abstract, Tables 1–6 with captions inside their floats, Figures 1–3 placed in their sections, citations resolved (no `[?]`), and the bibliography.
- `../scripts/check_latex.py` passes its static checks.

**Do not edit the `.tex` by hand.** Edit `../manuscript.md` and regenerate:

```
python paper/scripts/split_sections.py
python paper/scripts/md_to_latex.py
python paper/scripts/md_to_latex.py --anonymous
python paper/scripts/check_latex.py
python paper/scripts/make_submission.py
tectonic -X compile paper/arxiv/main.tex
```

No arXiv identifier has been assigned. Upload contents are listed in `ARXIV_UPLOAD_MANIFEST.txt`.
