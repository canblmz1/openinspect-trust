"""Paper figures from the frozen final CSVs (reports/m7_final). No model is run."""
import ast
from pathlib import Path
import numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg"); import matplotlib.pyplot as plt
ROOT = Path(__file__).resolve().parents[2]; F = ROOT / "reports/m7_final"; OUT = ROOT / "paper/figures"; OUT.mkdir(exist_ok=True)
plt.rcParams.update({"font.size": 9.5, "axes.spines.top": False, "axes.spines.right": False})
col = {"D0": "#1f4e79", "D1": "#b8860b", "D2": "#2e7d32"}; mk = {"D0": "o", "D1": "s", "D2": "^"}; off = {"D0": -0.2, "D1": 0, "D2": 0.2}

# Figure 1: gain by exposure stratum
dr = pd.read_csv(F / "FINAL_DOSE_RESPONSE.csv"); dr = dr[dr.bin.str.startswith(("control", "probe"))]
bins = ["control", "probe delta<0.02", "probe 0.02-0.08", "probe delta>0.08"]
fig, axes = plt.subplots(1, 2, figsize=(10, 4.2), sharey=True)
for ax, rep in zip(axes, ["DINOv2-small", "DINOv2-base"]):
    labels = []
    for i, b in enumerate(bins):
        ns = []
        for d in ["D0", "D1", "D2"]:
            r = dr[(dr.design == d) & (dr.representation == rep) & (dr.bin == b)].iloc[0]
            ps = ast.literal_eval(r.per_seed); ns.append(int(r.n_images))
            ax.scatter([i + off[d]] * len(ps), ps, marker=mk[d], color=col[d], alpha=.6, s=24, label=d if i == 0 else None)
            ax.plot([i + off[d] - .08, i + off[d] + .08], [np.mean(ps)] * 2, color=col[d], lw=2.2)
        name = {"control": "controls\n(unexposed)", "probe delta<0.02": "probes\nΔ < 0.02", "probe 0.02-0.08": "probes\n0.02 ≤ Δ ≤ 0.08", "probe delta>0.08": "probes\nΔ > 0.08"}[b]
        labels.append(f"{name}\nn = {min(ns)}–{max(ns)}")
    ax.axhline(0, color="k", lw=.7); ax.set_xticks(range(4)); ax.set_xticklabels(labels, fontsize=8.5)
    ax.set_title(f"exposure Δ measured with {rep}", fontsize=9.5)
axes[0].set_ylabel("C0 − C1 mAP50-95 (percentage points)")
axes[0].legend(frameon=False, fontsize=8, loc="upper left", title="design", title_fontsize=8)
fig.text(0.5, 0.005, "Markers: per-seed C0−C1 difference (8 matched seed pairs: D0×3, D1×3, D2×2); bars: mean over seeds of each design; no interval shown. "
         "n = test images per design. Δ = max cosine to C0 training images − max cosine to C1 training images; bins fixed before the last three seed pairs were trained.",
         ha="center", fontsize=7, wrap=True)
fig.tight_layout(rect=(0, 0.06, 1, 1)); fig.savefig(OUT / "fig1_exposure_gain.png", dpi=220); plt.close(fig)

# Figure 2: source shift
ss = pd.DataFrame({"source": ["DsPCBSD+\n(held-out n = 1,768)", "PCB-IND\n(n = 1,713)", "PCB-Defect\n(n = 939)"],
                   "in": [43.74, 56.82, 47.62], "held": [16.37, 19.17, 0.33]})
fig, ax = plt.subplots(figsize=(7.2, 4.0)); x = np.arange(3)
ax.bar(x - .19, ss["in"], .38, color="#1f4e79", label="in-distribution: same-source test images, model trained with the source")
ax.bar(x + .19, ss.held, .38, color="#c0504d", label="source held out (B-strict, model never saw the source)")
for i, (a, b) in enumerate(zip(ss["in"], ss.held)):
    ax.text(i - .19, a + 1, f"{a:.1f}", ha="center", fontsize=8); ax.text(i + .19, b + 1, f"{b:.1f}", ha="center", fontsize=8)
ax.set_xticks(x); ax.set_xticklabels(ss.source, fontsize=8.5); ax.set_ylabel("mAP50-95 (%)"); ax.set_ylim(0, 70)
ax.legend(frameon=False, fontsize=7.5, loc="upper right")
fig.text(0.5, 0.01, "One seed per model. In-distribution reference: other test images of the same source\n(A1 split for DsPCBSD+ and PCB-IND; A0 split for PCB-Defect).", ha="center", fontsize=6.8)
fig.tight_layout(rect=(0, 0.07, 1, 1)); fig.savefig(OUT / "fig2_source_shift.png", dpi=220); plt.close(fig)

# Figure 3: replication per design and seed
rep = pd.read_csv(F / "FINAL_REPLICATION_TABLE.csv"); rep = rep[rep.seed.astype(str).str.fullmatch(r"\d")]
fig, ax = plt.subplots(figsize=(8.2, 3.8)); xs = []; xl = []; k = 0
for d in ["D0", "D1", "D2"]:
    for _, r in rep[rep.design == d].iterrows():
        ax.scatter(k - .12, r.probe, marker="o", color="#1f4e79", s=30); ax.scatter(k + .12, r.control, marker="x", color="#c0504d", s=34)
        ax.plot([k - .12, k + .12], [r.probe, r.control], color="grey", lw=.8, alpha=.6)
        xs.append(k); xl.append(f"{d}\nseed {r.seed}"); k += 1
    k += .6
ax.scatter([], [], marker="o", color="#1f4e79", label="probes (exposed in C0)"); ax.scatter([], [], marker="x", color="#c0504d", label="controls (unexposed)")
ax.axhline(0, color="k", lw=.7); ax.set_xticks(xs); ax.set_xticklabels(xl, fontsize=8); ax.set_ylabel("C0 − C1 mAP50-95 (percentage points)")
ax.legend(frameon=False, fontsize=8); ax.set_title("Probe and control differences for every matched seed pair (no pair omitted)", fontsize=9.5)
fig.tight_layout(); fig.savefig(OUT / "fig3_replication.png", dpi=220); plt.close(fig)
print("ok")
