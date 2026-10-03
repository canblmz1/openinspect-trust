# Provenance copy of an analysis script from the 2026-10-03 independent review. Local paths are redacted
# (<REPO>, <SCRATCH>, <LOCAL>); the maintained, runnable versions are in reports/m7_final/scripts/.
"""Final AI-adjudicated labels, control performance, group validity, representation stability."""
import hashlib, json, sys
from pathlib import Path
import numpy as np
import pandas as pd

SCR = Path(sys.argv[1]); S = SCR / "review"
REPO = Path("<REPO>")
EXT = Path("C:/data/openinspect/extracted")
EMB = Path("C:/data/openinspect/embeddings")
OUT = REPO / "reports/m7_independent_review"; OUT.mkdir(parents=True, exist_ok=True)

items = {it["item"]: it for it in json.loads((S / "items.json").read_text())}
m = pd.read_csv(S / "merged.csv", index_col=0)
adj_key = json.loads((S / "key_J.json").read_text())
rows = [l.split(",", 3) for l in (S / "adj.csv").read_text().splitlines()[1:] if l.strip()]
adj = pd.DataFrame(rows, columns=["code", "label", "confidence", "rationale"])
adj["item"] = adj.code.map(adj_key); adj = adj.set_index("item")
RANK = {"HIGH": 2, "MEDIUM": 1, "LOW": 0}; INV = {v: k for k, v in RANK.items()}


def final(i):
    r = m.loc[i]
    if i in adj.index and r.A_label != r.B_label:
        a = adj.loc[i]; return a.label, a.confidence, "adjudicated", a.rationale
    if r.A_label == r.B_label:
        c = INV[min(RANK[r.A_confidence], RANK[r.B_confidence])]
        return r.A_label, c, "agreed", r.A_rationale
    raise RuntimeError(i)


f = pd.DataFrame([final(i) for i in m.index], index=m.index, columns=["final_label", "final_confidence", "final_basis", "final_rationale"])
m = m.join(f)

# ---------- controls ----------
ctl = m[m.kind != "candidate"].copy()
ctl["a"] = [items[i]["a"] for i in ctl.index]; ctl["b"] = [items[i]["b"] for i in ctl.index]
ctl["expected"] = ctl.kind.map({"positive_synthetic": "A (B acceptable)", "negative_cross_source": "E (D acceptable)",
                                "negative_random_within_source": "D or E"})
ctl[["kind", "a", "b", "expected", "A_label", "A_confidence", "B_label", "B_confidence", "A_rationale", "B_rationale"]].rename_axis("control_id").to_csv(OUT / "POSITIVE_NEGATIVE_CONTROLS.csv")
cperf = {}
for tag in "AB":
    pos = ctl[ctl.kind == "positive_synthetic"][f"{tag}_label"]; neg = ctl[ctl.kind != "positive_synthetic"][f"{tag}_label"]
    cperf[tag] = {"positives": int(len(pos)), "pos_called_A": int((pos == "A").sum()), "pos_called_AB": int(pos.isin(["A", "B"]).sum()),
                  "pos_called_ABC": int(pos.isin(list("ABC")).sum()),
                  "negatives": int(len(neg)), "neg_called_AB": int(neg.isin(["A", "B"]).sum()), "neg_called_ABC": int(neg.isin(list("ABC")).sum())}

# ---------- candidates ----------
cand = pd.read_csv(REPO / "artifacts/m3/review-candidates.csv").set_index("pair_id")
c = cand.join(m[m.kind == "candidate"][["A_label", "A_confidence", "B_label", "B_confidence", "final_label", "final_confidence", "final_basis", "final_rationale"]])
assert c.final_label.notna().all() and len(c) == 300


def sha(ref):
    src, rel = ref.split("/", 1)
    return hashlib.sha256((EXT / src / rel).read_bytes()).hexdigest()


def emb(model, h):
    d = next((EMB / model).glob("v1/*"))
    v = np.load(d / h[:2] / f"{h}.npy").astype(np.float64); return v / np.linalg.norm(v)


SM, BA = "facebook--dinov2-small@ed25f3a31f01", "facebook--dinov2-base@f9e44c814b77"
cs, cb = [], []
for pid, r in c.iterrows():
    ha, hb = sha(f"{r.source_a}/{r.image_a}"), sha(f"{r.source_b}/{r.image_b}")
    cs.append(float(emb(SM, ha) @ emb(SM, hb))); cb.append(float(emb(BA, ha) @ emb(BA, hb)))
c["cosine_small_recomputed"] = cs; c["cosine_base"] = cb
thr = json.loads((REPO / "artifacts/m3/thresholds.json").read_text())
BASE_FAMILY, BASE_NEAR = 0.958, 0.958  # M5.5 calibrated base thresholds (reports/m5_5/representation-sensitivity.md)
c["base_above_threshold"] = c.cosine_base >= BASE_FAMILY
c["dup_like"] = c.final_label.isin(["A", "B"]); c["related"] = c.final_label.isin(["A", "B", "C"])
c["unrelated"] = c.final_label.isin(["D", "E"]); c["ambiguous"] = c.final_label == "F"
c["pair_kind"] = np.where(c.source.str.contains(r"\|"), "cross-source", "same-source")
c["phash_bin"] = pd.cut(c.phash_distance, [-1, 4, 10, 20, 64], labels=["0-4", "5-10", "11-20", ">20"])
c["cos_bin"] = pd.cut(c.cosine, [0, 0.85, 0.918, 0.934, 0.96, 1.0], labels=["<0.85", "0.85-0.918", "0.918-0.934", "0.934-0.96", ">=0.96"])
c.rename_axis("pair_id").to_csv(OUT / "VISUAL_REVIEW_300.csv")


def wilson(k, n, z=1.96):
    if n == 0: return (np.nan, np.nan)
    p = k / n; d = 1 + z * z / n; ctr = (p + z * z / (2 * n)) / d; h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (ctr - h, ctr + h)


def table(by):
    rows = []
    for key, g in c.groupby(by, observed=True):
        n = len(g); r = {"group": key if not isinstance(key, tuple) else " / ".join(map(str, key)), "n": n}
        for col, name in [("dup_like", "A+B"), ("related", "A+B+C"), ("unrelated", "D+E"), ("ambiguous", "F")]:
            k = int(g[col].sum()); lo, hi = wilson(k, n); r[name] = f"{k} ({100*k/n:.0f}%, {100*lo:.0f}-{100*hi:.0f})"
        rows.append(r)
    return pd.DataFrame(rows)


tabs = {name: table(by) for name, by in [("machine_category", "machine_category"), ("source", "source"),
                                          ("pair_kind", "pair_kind"), ("cosine_bin", "cos_bin"), ("phash_bin", "phash_bin"),
                                          ("base_above", "base_above_threshold"), ("category_x_source", ["machine_category", "source"])]}
for k, t in tabs.items():
    t.to_csv(S / f"validity_{k}.csv", index=False)
    print("\n##", k); print(t.to_string(index=False))
print(json.dumps(cperf, indent=1))
print(pd.crosstab(c.machine_category, c.final_label))
print("final label counts", c.final_label.value_counts().to_dict(), "basis", c.final_basis.value_counts().to_dict())
print("cosine recompute max abs diff", float((c.cosine - c.cosine_small_recomputed).abs().max()))
json.dump({"controls": cperf}, open(S / "controls.json", "w"), indent=1)
# stability: among primary-level pairs (NEAR/SAME_FAMILY), visual verdict vs base threshold
prim = c[c.machine_category.isin(["NEAR_DUPLICATE", "SAME_FAMILY_OR_SCENE"])]
print(pd.crosstab([prim.final_label], prim.base_above_threshold))
print(pd.crosstab([c.final_label], c.base_above_threshold))
