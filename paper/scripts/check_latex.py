"""Static checks of the generated LaTeX (no TeX toolchain is installed): non-ASCII, leftover Markdown,
citation keys present in references.bib, brace balance, figure files present, anonymity."""
import re
from pathlib import Path

A = Path(__file__).resolve().parents[1] / "arxiv"
bib = set(re.findall(r"@\w+\{([^,]+),", (A / "references.bib").read_text(encoding="utf-8")))
ok = True
for name in ["main.tex", "main_anonymous.tex"]:
    t = (A / name).read_text(encoding="utf-8")
    nonascii = sorted({c for c in t if ord(c) > 127})
    md = len(re.findall(r"\*\*", t)) + len(re.findall(r"(?<!\\)`(?!`)", t.replace("``", "")))
    keys = {k.strip() for g in re.findall(r"\\cite\{([^}]*)\}", t) for k in g.split(",")}
    missing = keys - bib
    stripped = re.sub(r"\\[{}]", "", t)
    balanced = stripped.count("{") == stripped.count("}")
    figs = re.findall(r"\\includegraphics\[[^]]*\]\{([^}]*)\}", t)
    figs_missing = [f for f in figs if not (A / f).exists()]
    anon_leak = [w for w in ["github.com", "EVREN", "SSYZ", "canblmz1"] if w in t] if "anonymous" in name else []
    print(f"{name}: non-ascii={nonascii} leftover-md={md} cite-keys={len(keys)} missing-keys={sorted(missing)} "
          f"braces-balanced={balanced} figures={len(figs)} figures-missing={figs_missing} anonymity-leaks={anon_leak}")
    ok &= not nonascii and not md and not missing and balanced and not figs_missing and not anon_leak
print("STATIC CHECK", "PASS" if ok else "FAIL")
