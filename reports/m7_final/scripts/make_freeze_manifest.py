"""Write reports/m7_final/FINAL_FREEZE_MANIFEST.md: SHA-256 of the frozen analysis inputs, outputs, figures and paper files."""
import datetime as dt, hashlib, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]; F = ROOT / "reports/m7_final"
def sha(p):
    # Hash the bytes as committed (the index blob, LF line endings per .gitattributes); fall back to the working tree.
    r = subprocess.run(["git", "show", f":{p.relative_to(ROOT).as_posix()}"], cwd=ROOT, capture_output=True)
    return hashlib.sha256(r.stdout if r.returncode == 0 else p.read_bytes()).hexdigest()
def git(*a):
    try: return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    except Exception: return "?"
groups = {
    "Dataset release and design inputs": [ROOT / "manifests/releases/v0.1/release.json", ROOT / "manifests/releases/v0.1/items.parquet",
        ROOT / "manifests/releases/v0.1/annotations.parquet", *sorted((ROOT / "manifests/experiments/v0.1").glob("*.csv"))],
    "Analysis scripts": [*sorted((F / "scripts").glob("*.py")), ROOT / "scripts/m7_evaluate.py", *sorted((ROOT / "paper/scripts").glob("*.py"))],
    "Final result files": [*sorted(F.glob("FINAL_*.csv")), F / "replication_summary.csv", F / "probe_link_split.csv", F / "visual_category_gain_D0.csv",
        F / "analysis_meta.json", *sorted((F / "public").glob("*.csv")),
        ROOT / "reports/m7_independent_review/AI_PM_ADJUDICATED.csv", ROOT / "reports/m7_independent_review/data/exposure.csv"],
    "Figures": sorted((ROOT / "paper/figures").glob("*.png")),
    "Paper files": [ROOT / "paper/manuscript.md", ROOT / "paper/arxiv/main.tex", ROOT / "paper/arxiv/main_anonymous.tex", ROOT / "paper/arxiv/references.bib", ROOT / "paper/arxiv/main.pdf", ROOT / "paper/arxiv/main_anonymous.pdf", ROOT / "paper/arxiv/ARXIV_UPLOAD_MANIFEST.txt",
        *sorted((ROOT / "paper/tables").glob("*.md")), *sorted((ROOT / "paper/submission").glob("*"))],
    "Final reports": [*(p for p in sorted(F.glob("FINAL_*.md")) if p.name != "FINAL_FREEZE_MANIFEST.md"), F / "PUBLICATION_CONSISTENCY_AUDIT.md", F / "PUBLICATION_RELEASE_CHECKLIST.md",
        ROOT / "paper/CITATION_AUDIT.md", ROOT / "paper/FINAL_REVIEWER_2_AUDIT.md"],
}
L = ["# Final freeze manifest: OpenInspect-Trust M7", "",
     f"- **Date:** {dt.date(2026, 10, 3).isoformat()} (generated {dt.datetime.now().strftime('%Y-%m-%d %H:%M')})",
     f"- **Git base commit:** `{git('rev-parse', 'HEAD')}` ({git('log', '-1', '--format=%cd')}). The frozen files below are committed on top of this base in the publication-freeze commits, tagged `research-m7-final` (annotated).",
     "- **Dataset release:** OpenInspect-Trust v0.1 (4,420 images, 5,297 boxes); manifest hashes below.",
     "- **Experiment status:** **FROZEN — NO FURTHER TRAINING PLANNED**",
     "- **Human validation status:** **NOT PERFORMED**",
     "- **AI visual adjudication status:** **COMPLETED** (300 M3 candidate pairs; 90 probe–mate and control pairs, two blinded AI passes and adjudication)",
     "- **Scientific verdict:** B — WORKSHOP / PREPRINT READY",
     "- **Models:** 31 platform jobs; 25 checkpoints used (SHA-256 in `public/CHECKPOINT_MANIFEST_PUBLIC.csv`; one effective-configuration hash); Ultralytics 8.3.0 evaluation.",
     "- **Verification:** the final analysis was re-run from the sanitised scripts and reproduced every statistic (`PUBLICATION_CONSISTENCY_AUDIT.md`).", ""]
for g, files in groups.items():
    L += [f"## {g}", "", "| file | SHA-256 |", "|---|---|"]
    for p in files:
        if p.exists() and p.is_file():
            L.append(f"| `{p.relative_to(ROOT).as_posix()}` | `{sha(p)}` |")
    L.append("")
L.append("This manifest does not hash itself.")
(F / "FINAL_FREEZE_MANIFEST.md").write_text("\n".join(L) + "\n", encoding="utf-8")
print("written", sum(1 for l in L if l.startswith("| `")), "hashes")
