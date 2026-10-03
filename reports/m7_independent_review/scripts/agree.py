import csv, json, sys
from pathlib import Path
import numpy as np
import pandas as pd

S = Path(sys.argv[1]) / "review"
items = {it["item"]: it for it in json.loads((S / "items.json").read_text())}
out = {}
for tag in "AB":
    key = json.loads((S / f"key_{tag}.json").read_text())
    rows = [l.split(",", 3) for l in (S / f"pass{tag}.csv").read_text().splitlines()[1:] if l.strip()]
    df = pd.DataFrame(rows, columns=["code", "label", "confidence", "rationale"])
    assert len(df) == len(key) == df.code.nunique(), (tag, len(df), len(key))
    df["item"] = df.code.map(key)
    assert df.item.notna().all()
    out[tag] = df.set_index("item")[["label", "confidence", "rationale"]].add_prefix(f"{tag}_")
m = out["A"].join(out["B"])
m["kind"] = [items[i]["kind"] for i in m.index]
L = list("ABCDEF")
cm = pd.crosstab(m.A_label, m.B_label).reindex(index=L, columns=L, fill_value=0)


def kappa(a, b, labels, weights=None):
    n = len(a)
    idx = {l: i for i, l in enumerate(labels)}
    O = np.zeros((len(labels),) * 2)
    for x, y in zip(a, b):
        O[idx[x], idx[y]] += 1
    O /= n
    E = np.outer(O.sum(1), O.sum(0))
    k = len(labels)
    if weights == "linear":
        W = np.abs(np.subtract.outer(range(k), range(k))) / (k - 1)
    else:
        W = 1 - np.eye(k)
    return 1 - (W * O).sum() / (W * E).sum()


cand = m[m.kind == "candidate"]
res = {}
for name, d in [("all_342", m), ("candidates_300", cand)]:
    a, b = d.A_label.tolist(), d.B_label.tolist()
    # ordinal A..E (F treated as missing for weighted)
    keep = [(x, y) for x, y in zip(a, b) if x != "F" and y != "F"]
    res[name] = {
        "n": len(d), "exact_agreement": float(np.mean(np.array(a) == np.array(b))),
        "cohen_kappa_6": float(kappa(a, b, L)),
        "linear_weighted_kappa_AtoE": float(kappa(*zip(*keep), list("ABCDE"), "linear")),
        "related_vs_not_agreement": float(np.mean([(x in "ABC") == (y in "ABC") for x, y in zip(a, b)])),
        "related_vs_not_kappa": float(kappa(["R" if x in "ABC" else "N" for x in a],
                                              ["R" if y in "ABC" else "N" for y in b], ["R", "N"])),
        "AB_vs_rest_kappa": float(kappa(["R" if x in "AB" else "N" for x in a],
                                         ["R" if y in "AB" else "N" for y in b], ["R", "N"])),
    }
# bootstrap CI for kappa on candidates
rng = np.random.default_rng(0)
ks = []
ca, cb = cand.A_label.values, cand.B_label.values
for _ in range(2000):
    ix = rng.integers(0, len(cand), len(cand))
    ks.append(kappa(ca[ix], cb[ix], L))
res["candidates_300"]["cohen_kappa_6_ci95"] = [float(np.percentile(ks, 2.5)), float(np.percentile(ks, 97.5))]
print(json.dumps(res, indent=1))
print(cm)
print(pd.crosstab(m.kind, [m.A_label]).to_string())
print(pd.crosstab(m.kind, [m.B_label]).to_string())
m.to_csv(S / "merged.csv")
cm.to_csv(S / "disagreement_matrix.csv")
(S / "agreement.json").write_text(json.dumps(res, indent=1))
