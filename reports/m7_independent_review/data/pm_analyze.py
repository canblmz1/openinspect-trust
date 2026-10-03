# Provenance copy of an analysis script from the 2026-10-03 independent review. Local paths are redacted
# (<REPO>, <SCRATCH>, <LOCAL>); the maintained, runnable versions are in reports/m7_final/scripts/.
"""Unblind the two AI review passes, compute agreement, then (after adjudication) join with similarity and gain."""
import csv, json, sys
from pathlib import Path
import numpy as np
import pandas as pd

R = Path(__file__).parent
REPO = Path("<REPO>")
OUT = REPO / "reports/m7_independent_review"
sys.path.insert(0, str(R.parent))
L = list("ABCDEFG")
GROUPS = {"duplicate-like (A)": "A", "same-instance-like (A+B)": "AB", "same-family-like (A+B+C)": "ABC",
          "meaningfully-related (A–D)": "ABCD", "not-meaningfully-related (E+F)": "EF", "ambiguous (G)": "G"}
BROAD = {"A": "instance", "B": "instance", "C": "family", "D": "structural", "E": "none", "F": "none", "G": "ambiguous"}

it = {x["item"]: x for x in json.load(open(REPO / "reports/m7_independent_review/data/pm_items.json"))}
items = pd.read_parquet(REPO / "manifests/releases/v0.1/items.parquet").set_index("global_id"); items["source"] = items.source.astype(str)


def load(tag):
    key = json.load(open(R / "keys" / f"key_{tag}.json"))
    df = pd.read_csv(R / f"review_{tag}.csv", dtype=str)
    df.columns = [c.strip() for c in df.columns]
    df["category"] = df.category.str.strip().str.upper().str[0]
    df["confidence"] = df.confidence.str.strip().str.upper()
    assert len(df) == 90 and df.code.nunique() == 90 and set(df.code) == set(key), (tag, len(df))
    assert df.category.isin(L).all(), df.category.unique()
    df["pair_id"] = df.code.map(key)
    return df.set_index("pair_id")


def kappa(a, b, labels, weights=None):
    idx = {l: i for i, l in enumerate(labels)}; k = len(labels)
    O = np.zeros((k, k))
    for x, y in zip(a, b):
        O[idx[x], idx[y]] += 1
    O /= O.sum(); E = np.outer(O.sum(1), O.sum(0))
    W = (np.abs(np.subtract.outer(range(k), range(k))) / (k - 1)) if weights == "linear" else 1 - np.eye(k)
    return float(1 - (W * O).sum() / (W * E).sum())


def agreement(df):
    a, b = df.cat_A.values, df.cat_B.values
    res = {"n": len(df), "exact": float((a == b).mean()), "kappa_7": kappa(a, b, L)}
    keep = (a != "G") & (b != "G")
    res["linear_weighted_kappa_A_to_F_excl_G"] = kappa(a[keep], b[keep], list("ABCDEF"), "linear")
    ba, bb = [BROAD[x] for x in a], [BROAD[x] for x in b]
    res["broad_agreement(instance/family/structural/none/ambiguous)"] = float(np.mean(np.array(ba) == np.array(bb)))
    res["broad_kappa"] = kappa(ba, bb, ["instance", "family", "structural", "none", "ambiguous"])
    for name, s in GROUPS.items():
        xa, xb = np.isin(a, list(s)), np.isin(b, list(s))
        res[f"{name}: agreement"] = float((xa == xb).mean())
        res[f"{name}: kappa"] = kappa(xa, xb, [True, False]) if (xa.any() or xb.any()) and not (xa.all() and xb.all()) else None
        res[f"{name}: A-count/B-count"] = [int(xa.sum()), int(xb.sum())]
    rng = np.random.default_rng(0); ks = []
    for _ in range(2000):
        ix = rng.integers(0, len(a), len(a)); ks.append(kappa(a[ix], b[ix], L))
    res["kappa_7_ci95"] = [float(np.percentile(ks, 2.5)), float(np.percentile(ks, 97.5))]
    return res


A, B = load("A"), load("B")
df = pd.DataFrame({"probe_id": [it[i]["a"] for i in A.index], "mate_id": [it[i]["b"] for i in A.index],
                   "kind": [it[i]["kind"] for i in A.index]}, index=A.index)
df["cat_A"], df["conf_A"], df["reason_A"] = A.category, A.confidence, A.visual_reason
df["cat_B"], df["conf_B"], df["reason_B"] = B.category, B.confidence, B.visual_reason
df["source"] = df.probe_id.map(items.source) + np.where(df.probe_id.map(items.source) != df.mate_id.map(items.source), "|" + df.mate_id.map(items.source), "")
stage = sys.argv[1] if len(sys.argv) > 1 else "agree"

if stage == "agree":
    res = {"all_90": agreement(df), "probe_pairs_60": agreement(df[df.kind.str.startswith("probe")]),
           "control_pairs_30": agreement(df[df.kind.str.startswith("control")])}
    cm = pd.crosstab(df.cat_A, df.cat_B).reindex(index=L, columns=L, fill_value=0)
    json.dump(res, open(R / "agreement.json", "w"), indent=1); cm.to_csv(R / "confusion.csv")
    print(json.dumps(res, indent=1)); print(cm)
    print("disagreements:", int((df.cat_A != df.cat_B).sum()))
    df.to_csv(R / "merged.csv")
    sys.exit()

# ---------------- final stage (after adjudication) ----------------
adj = pd.read_csv(R / "adjudication.csv", dtype=str).set_index("pair_id")
df["final_category"] = np.where(df.cat_A == df.cat_B, df.cat_A, None)
df["adjudication_reason"] = np.where(df.cat_A == df.cat_B, "agreed in both blinded passes", "")
df["same_board_relation"] = ""; df["adj_confidence"] = ""
for pid, r in adj.iterrows():
    df.loc[pid, "final_category"] = r.final_category.strip()
    df.loc[pid, "adjudication_reason"] = r.adjudication_reason; df.loc[pid, "adj_confidence"] = r.confidence
    if "same_board_relation" in adj.columns:
        df.loc[pid, "same_board_relation"] = (r.get("same_board_relation") if isinstance(r.get("same_board_relation"), str) else "")
assert df.final_category.isin(L).all()
df.to_csv(R / "final.csv")
print(df.final_category.value_counts().reindex(L, fill_value=0).to_dict())
print(pd.crosstab(df.kind, df.final_category).reindex(columns=L, fill_value=0))
