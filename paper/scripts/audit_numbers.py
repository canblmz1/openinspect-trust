"""Cross-check the numbers in paper/manuscript.md tables 1-3 against the frozen CSVs (2-decimal rounding of exact values),
and scan the paper, README and final reports for known stale values. Exit code 1 on any mismatch."""
import re, sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]; F = ROOT / "reports/m7_final"
md = (ROOT / "paper/manuscript.md").read_text(encoding="utf-8")
num = lambda s: float(s.replace("−", "-").replace("+", "").replace("**", "").strip())
bad = []

def table_after(caption):
    i = md.index(caption); rows = []
    for line in md[i:].splitlines()[1:]:
        if line.startswith("|"):
            rows.append([c.strip() for c in line.strip("|").split("|")])
        elif rows:
            break
    return rows[2:]

rep = pd.read_csv(F / "FINAL_REPLICATION_TABLE.csv"); rep = rep[rep.seed.astype(str).str.fullmatch(r"\d")]
for r in table_after("**Table 1."):
    if r[0].startswith("unweighted"):
        exp = [rep.overall.mean(), rep.probe.mean(), rep.control.mean(), rep.probe_minus_control.mean()]
    else:
        x = rep[(rep.design == r[0]) & (rep.seed.astype(int) == int(r[1]))].iloc[0]
        exp = [x.overall, x.probe, x.control, x.probe_minus_control]
    for got, e in zip(r[2:6], exp):
        if abs(num(got) - round(e, 2)) > 1e-9: bad.append(f"Table 1 {r[0]} {r[1]}: manuscript {got} vs CSV {e:.4f}")

sa = pd.read_csv(F / "FINAL_SEED_AWARE_STATS.csv")
name = {"D0 probes (primary)": ("D0", "probe"), "D0 overall": ("D0", "overall"), "D0 probes − controls": ("D0", "probe_minus_control"),
        "D1 probes": ("D1", "probe"), "D1 probes − controls": ("D1", "probe_minus_control"), "D2 probes": ("D2", "probe"),
        "D2 probes − controls": ("D2", "probe_minus_control"), "pooled probes (3 designs)": ("pooled D0+D1+D2 (inverse-variance)", "probe"),
        "pooled probes − controls": ("pooled D0+D1+D2 (inverse-variance)", "probe_minus_control"), "pooled overall": ("pooled D0+D1+D2 (inverse-variance)", "overall")}
for r in table_after("**Table 2."):
    key = r[0].replace("**", "")
    d, q = name[key]; x = sa[(sa.design == d) & (sa.estimand == q)].iloc[0]
    checks = [(r[2], x.point_mean)]
    if r[3]: checks += list(zip(r[3].split(","), [x.A_test_sampling_lo, x.A_test_sampling_hi]))
    if r[4]: checks += list(zip(r[4].split(","), [x.B_seed_t_lo, x.B_seed_t_hi]))
    checks += list(zip(r[5].replace("**", "").split(","), [x.C_combined_two_stage_lo, x.C_combined_two_stage_hi]))
    if r[6]: checks.append((r[6], x.C_combined_P_le_0))
    for got, e in checks:
        nd = 3 if got.strip().startswith("0.") else 2
        if abs(num(got) - round(e, nd)) > 1e-9: bad.append(f"Table 2 {key}: manuscript {got.strip()} vs CSV {e:.4f}")

pl = pd.read_csv(F / "FINAL_PLACEBO_RESULTS.csv")
for r in table_after("**Table 3."):
    x = pl[pl.design == r[0]].iloc[0]
    m, sd = re.match(r"(\S+) \((\S+)\)", r[3]).groups()
    for got, e, nd in [(r[2], x.observed_probe_minus_control, 2), (m, x.null_mean, 2), (sd, x.null_sd, 2), (r[4], x.p_one_sided, 3), (r[5], x.p_two_sided, 3)]:
        if abs(num(got) - round(e, nd)) > 1e-9: bad.append(f"Table 3 {r[0]}: manuscript {got} vs CSV {e:.4f}")

stale = ["−0.68 to +8.46", "+0.67 to +7.45", "0.008", "p ≈ 0.35", "+0.24 to +3.82", "+1.06 to +7.33", "flatbed", "hobby", "DIY", "noise__"]
private_inv = F / "inventory_after" / "evren_run_inventory.csv"  # private file; if present, also forbid job-ID fragments
if private_inv.exists():
    stale += sorted({m[-8:] for m in re.findall(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", private_inv.read_text(encoding="utf-8"))})
for f in [ROOT / "paper/manuscript.md", ROOT / "README.md", *F.glob("FINAL_*.md"), F / "EVREN_SAYZEK_TECHNICAL_BRIEF_TR.md", F / "OPENINSPECT_FINAL_ONE_PAGE_TR.md", *(ROOT / "paper/submission").glob("*")]:
    t = f.read_text(encoding="utf-8")
    for s in stale:
        if s in t: bad.append(f"stale value '{s}' in {f.relative_to(ROOT)}")
print("\n".join(bad) if bad else "ALL CHECKED NUMBERS MATCH; no stale values found")
sys.exit(1 if bad else 0)
