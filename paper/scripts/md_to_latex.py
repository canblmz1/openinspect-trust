"""Convert paper/manuscript.md to paper/arxiv/main.tex (limited Markdown subset used by the manuscript).

Handles: ## / ### headings, paragraphs, **bold**, *italic*, `code`, '-' lists, pipe tables, [n] citations
(mapped to BibTeX keys), and the Unicode symbols used in the text. The abstract becomes \\begin{abstract};
the hand-written References section is replaced by \\bibliography{references}.
Usage: python paper/scripts/md_to_latex.py [--anonymous]
"""
import re, shutil, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "paper/manuscript.md"
OUT = ROOT / "paper/arxiv"
ANON = "--anonymous" in sys.argv
KEYS = {1: "barz2020", 2: "laroca2023", 3: "tampu2022", 4: "figueiredo2024", 5: "joeres2025datasail", 6: "babu2024leakage",
        7: "zhang2023aebad", 8: "pemula2025robustad", 9: "sun2017revisiting", 10: "sun2026unipcb", 11: "lv2024dspcbsd",
        12: "yan2026pcbind", 13: "rashid2025pcbdefect", 14: "oquab2024dinov2", 15: "jocher2024yolo11"}
UNI = {"−": "$-$", "–": "--", "—": "---", "Δ": "$\\Delta$", "≤": "$\\leq$", "≥": "$\\geq$", "ρ": "$\\rho$", "κ": "$\\kappa$",
       "×": "$\\times$", "↔": "$\\leftrightarrow$", "→": "$\\rightarrow$", "≈": "$\\approx$", "∈": "$\\in$", "’": "'", "“": "``", "”": "''", "%": "\\%"}


def esc(s):
    s = s.replace("\\", "\\textbackslash{}")
    for a, b in [("&", "\\&"), ("#", "\\#"), ("_", "\\_"), ("$", "\\$"), ("{", "\\{"), ("}", "\\}"), ("~", "\\textasciitilde{}"), ("^", "\\^{}")]:
        s = s.replace(a, b)
    for a, b in UNI.items():
        s = s.replace(a, b)
    return s


def inline(s):
    codes = []
    s = re.sub(r"`([^`]+)`", lambda m: codes.append(m.group(1)) or f"\x00{len(codes)-1}\x00", s)
    def cite(m):
        nums = []
        for part in m.group(1).split(","):
            part = part.strip()
            if "–" in part or "-" in part:
                a, b = re.split(r"[–-]", part); nums += list(range(int(a), int(b) + 1))
            else:
                nums.append(int(part))
        return "\x01" + ",".join(KEYS[n] for n in nums) + "\x01"
    s = re.sub(r"\[(\d+(?:\s*[,–-]\s*\d+)*)\]", cite, s)
    s = esc(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", s)
    s = re.sub(r"(?<![\\\w])\*(?!\s)(.+?)(?<!\s)\*", r"\\emph{\1}", s)
    s = re.sub("\x01([^\x01]+)\x01", r"~\\cite{\1}", s)
    s = re.sub("\x00(\\d+)\x00", lambda m: "\\texttt{" + esc(codes[int(m.group(1))]) + "}", s)
    return s


def table(rows, caption=None):
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows if not re.match(r"^\|\s*-", r)]
    n = len(cells[0])
    out = ["\\begin{table}[htbp]\\centering\\small"] + (["\\caption{" + inline(caption) + "}"] if caption else []) + ["\\begin{adjustbox}{max width=\\linewidth}", "\\begin{tabular}{" + "l" * n + "}", "\\toprule"]
    out.append(" & ".join(inline(c) for c in cells[0]) + " \\\\ \\midrule")
    for r in cells[1:]:
        out.append(" & ".join(inline(c) for c in (r + [""] * n)[:n]) + " \\\\")
    out += ["\\bottomrule", "\\end{tabular}", "\\end{adjustbox}", "\\end{table}"]
    return out


md = SRC.read_text(encoding="utf-8")
title = md.splitlines()[0].lstrip("# ").strip()
body = md.split("\n## Abstract", 1)[1]
abstract, rest = body.split("\n## 1. Introduction", 1)
rest = "## 1. Introduction" + rest
rest = rest.split("\n## References")[0]
if ANON:
    rest = re.sub(r"https://github\.com/\S+", "[anonymised repository]", rest)
    rest = rest.replace("the EVREN platform (SSYZ)", "a managed cloud training platform")

lines_out, para, lst, tbl = [], [], False, []
pending_caption = None

def flush():
    global para
    if para:
        lines_out.append(inline(" ".join(para))); lines_out.append(""); para = []

def convert(text):
    global lst, tbl, pending_caption
    for line in text.splitlines():
        if line.startswith("|"):
            flush(); tbl.append(line); continue
        if tbl:
            lines_out.extend(table(tbl, pending_caption)); tbl = []; pending_caption = None
        mcap = re.match(r"^\*\*(Table \d+\.\s.*?)\*\*$", line.strip())
        if mcap:
            flush(); pending_caption = re.sub(r"^Table \d+\.\s*", "", mcap.group(1)); continue
        if line.startswith("- "):
            flush()
            if not lst: lines_out.append("\\begin{itemize}"); lst = True
            lines_out.append("\\item " + inline(line[2:])); continue
        if lst and not line.startswith("- "):
            lines_out.append("\\end{itemize}"); lst = False
        m = re.match(r"^(#{2,4}) (.*)", line)
        if m:
            flush()
            t = re.sub(r"^\d+(\.\d+)?\.?\s+", "", m.group(2))
            cmd = {2: "section", 3: "subsection", 4: "subsubsection"}[len(m.group(1))]
            lines_out.append(f"\\{cmd}{{{inline(t)}}}"); continue
        if not line.strip():
            flush(); continue
        para.append(line.strip())
    flush()
    if tbl: lines_out.extend(table(tbl, pending_caption)); tbl = []; pending_caption = None
    if lst: lines_out.append("\\end{itemize}"); lst = False

convert(abstract)
abs_tex = "\n".join(lines_out); lines_out.clear()
convert(rest)
FIGS = ["\\begin{figure}[t]\\centering\\includegraphics[width=\\linewidth]{figures/fig1_exposure_gain.png}\\caption{C0$-$C1 mAP50-95 by exposure stratum (left: DINOv2-small; right: DINOv2-base). Markers: per-seed differences (8 matched seed pairs); bars: design means; no interval drawn. n = test images per design.}\\label{fig:exposure}\\end{figure}",
        "\\begin{figure}[t]\\centering\\includegraphics[width=0.8\\linewidth]{figures/fig2_source_shift.png}\\caption{In-distribution vs source-held-out mAP50-95 (one seed per model).}\\label{fig:source}\\end{figure}",
        "\\begin{figure}[t]\\centering\\includegraphics[width=0.9\\linewidth]{figures/fig3_replication.png}\\caption{Probe and control C0$-$C1 differences for every matched seed pair.}\\label{fig:replication}\\end{figure}"]
anchors = {"\\subsection{Group exposure and the probe/control contrast}": FIGS[2], "\\subsection{Exposure strength}": FIGS[0],
           "\\section{Source-Held-Out Evaluation}": FIGS[1]}
for k, v in anchors.items():
    i = lines_out.index(k); lines_out.insert(i + 1, v.replace("[t]", "[htbp]"))
figs = []
author = "Anonymous submission" if ANON else ("Can\\thanks{Code and data manifests: \\url{https://github.com/canblmz1/openinspect-trust}. "
                                               "Affiliation and contact e-mail to be added.}")
tex = f"""\\documentclass[11pt]{{article}}
\\usepackage[utf8]{{inputenc}}
\\usepackage[T1]{{fontenc}}
\\usepackage[margin=1in]{{geometry}}
\\usepackage{{graphicx,booktabs,amsmath,amssymb,adjustbox,hyperref}}
\\setlength{{\\emergencystretch}}{{3em}}
\\title{{{inline(title)}}}
\\author{{{author}}}
\\date{{}}
\\begin{{document}}
\\maketitle
\\begin{{abstract}}
{abs_tex}
\\end{{abstract}}
{chr(10).join(lines_out)}
{chr(10).join(figs)}
\\bibliographystyle{{plain}}
\\bibliography{{references}}
\\end{{document}}
"""
OUT.mkdir(parents=True, exist_ok=True)
name = "main_anonymous.tex" if ANON else "main.tex"
tex = tex.replace(" ~\\cite", "~\\cite")
tex = re.sub(r'"([^"\n]+)"', r"``\1''", tex)
(OUT / name).write_text(tex, encoding="utf-8")
(OUT / "figures").mkdir(exist_ok=True)
for f in (ROOT / "paper/figures").glob("*.png"):
    shutil.copy(f, OUT / "figures" / f.name)
print("wrote", OUT / name)
