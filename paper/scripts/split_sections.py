"""Regenerate the section files from paper/manuscript.md (the single source of truth)."""
import re
from pathlib import Path
P = Path(__file__).resolve().parents[1]; t = (P / "manuscript.md").read_text(encoding="utf-8")
d = {s.split("\n", 1)[0].strip(): "## " + s for s in re.split(r"(?m)^## ", t)[1:]}
hdr = "<!-- Generated from manuscript.md (single source of truth); do not edit separately. -->\n\n"
parts = {"abstract.md": ["Abstract"], "related_work.md": ["2. Related Work"],
         "methods.md": ["3. Datasets and Provenance", "4. Group Construction", "5. Controlled Experimental Design", "6. Training and Evaluation Protocol"],
         "results.md": ["7. Results", "8. Replication and Sensitivity", "9. Source-Held-Out Evaluation"], "limitations.md": ["10. Limitations"]}
for f, ks in parts.items():
    (P / f).write_text(hdr + "\n".join(d[k] for k in ks), encoding="utf-8")
print("sections ok")
