"""Build paper/submission/ from paper/manuscript.md (title, plain-text abstract, anonymised and named manuscripts)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
P = ROOT / "paper"; S = P / "submission"; S.mkdir(exist_ok=True)
md = (P / "manuscript.md").read_text(encoding="utf-8")
title = md.splitlines()[0].lstrip("# ").strip()
abstract = md.split("## Abstract", 1)[1].split("\n## 1.", 1)[0].strip()
plain = re.sub(r"\*\*(.+?)\*\*", r"\1", abstract)
plain = re.sub(r"\n- ", " ", plain)                     # bullet list -> running text
plain = re.sub(r"\n{2,}", "\n\n", plain).replace(":\n\n ", ": ").strip()
(S / "TITLE.txt").write_text(title + "\n", encoding="utf-8")
(S / "ABSTRACT.txt").write_text(plain + "\n", encoding="utf-8")
(S / "KEYWORDS.txt").write_text("benchmark assurance; train-test group exposure; data leakage; group-aware splitting; "
                                "industrial visual inspection; PCB defect detection; object detection; domain shift; "
                                "source-held-out evaluation; reproducibility\n", encoding="utf-8")
anon = md
anon = re.sub(r"https://github\.com/\S+", "[anonymised repository URL]", anon)
anon = anon.replace("the EVREN platform (SSYZ)", "a managed cloud training platform")
anon = anon.replace("EVREN", "the training platform")
head = "<!-- Anonymised for double-blind review: repository URL and training-platform name removed; no author names. -->\n\n"
(S / "ANONYMIZED_MANUSCRIPT.md").write_text(head + anon, encoding="utf-8")
named = md.replace(md.splitlines()[0], md.splitlines()[0] + "\n\nCan (GitHub: canblmz1) · Affiliation: to be added · Contact: to be added\n", 1)
(S / "NON_ANONYMIZED_MANUSCRIPT.md").write_text(named, encoding="utf-8")
leaks = [w for w in ["github.com", "EVREN", "SSYZ", "canblmz1"] if w in anon]
print("submission built; anonymity leaks:", leaks)
