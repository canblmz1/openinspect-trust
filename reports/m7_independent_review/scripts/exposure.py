# Provenance copy of an analysis script from the 2026-10-03 independent review. Local paths are redacted
# (<REPO>, <SCRATCH>, <LOCAL>); the maintained, runnable versions are in reports/m7_final/scripts/.
"""Per-test-item exposure strength (max cosine to C0 train vs C1 train), DINO-small and -base; probe-mate review sheets."""
import json, random, sys
from pathlib import Path
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

REPO = Path("<REPO>")
EMB = Path("C:/data/openinspect/embeddings")
REL = Path("C:/data/openinspect/release/v0.1/images")
S = Path(sys.argv[1]) / "review"
items = pd.read_parquet(REPO / "manifests/releases/v0.1/items.parquet").set_index("global_id")
V = {}
for tag, model in [("small", "facebook--dinov2-small@ed25f3a31f01"), ("base", "facebook--dinov2-base@f9e44c814b77")]:
    d = next((EMB / model).glob("v1/*"))
    X = np.stack([np.load(d / h[:2] / f"{h}.npy") for h in items.sha256_source]).astype(np.float32)
    V[tag] = X / np.linalg.norm(X, axis=1, keepdims=True)
gid = items.index.to_numpy(); pos = {g: i for i, g in enumerate(gid)}
rows = []
for dsg in range(3):
    r = pd.read_csv(REPO / f"manifests/experiments/v0.1/C-design{dsg}-roles.csv").set_index("id")
    c0 = pd.read_csv(REPO / f"manifests/experiments/v0.1/C0__design{dsg}.csv").set_index("id").split
    c1 = pd.read_csv(REPO / f"manifests/experiments/v0.1/C1__design{dsg}.csv").set_index("id").split
    test = c0[c0 == "test"].index
    tr0 = np.array([pos[g] for g in c0[c0 == "train"].index]); tr1 = np.array([pos[g] for g in c1[c1 == "train"].index])
    mates = np.array([pos[g] for g in r[r.role == "mate"].index])
    for tag in V:
        T = V[tag][[pos[g] for g in test]]
        s0 = T @ V[tag][tr0].T; s1 = T @ V[tag][tr1].T; sm = T @ V[tag][mates].T
        for i, g in enumerate(test):
            rows.append({"design": dsg, "rep": tag, "id": g, "role": r.role[g], "link": r.probe_link.get(g), "source": r.source[g],
                         "max_sim_C0": float(s0[i].max()), "max_sim_C1": float(s1[i].max()), "max_sim_mates": float(sm[i].max()),
                         "nearest_mate": gid[mates[sm[i].argmax()]], "nearest_C0": gid[tr0[s0[i].argmax()]], "nearest_C1": gid[tr1[s1[i].argmax()]]})
ex = pd.DataFrame(rows); ex["delta"] = ex.max_sim_C0 - ex.max_sim_C1
ex.to_csv(S.parent / "exposure.csv", index=False)
print(ex.groupby(["design", "rep", "role"])[["max_sim_C0", "max_sim_C1", "delta"]].describe().round(3).to_string())
print(ex[ex.rep == "small"].groupby(["design", "role", "link"], dropna=False).delta.agg(["count", "mean", "median"]).round(3))
for dsg in range(3):
    e = ex[(ex.design == dsg) & (ex.rep == "small") & (ex.role == "control")]
    print("design", dsg, "controls with delta>0.02:", int((e.delta > 0.02).sum()), "delta<-0.02:", int((e.delta < -0.02).sum()), "mean", round(e.delta.mean(), 4))

# ---------- targeted probe-mate review (design 0) ----------
e0 = ex[(ex.design == 0) & (ex.rep == "small")].set_index("id")
rng = random.Random(4242)
sel = []
for lt, k in [("crop sibling", 12), ("similar pair", 16), ("same component", 12), ("same metadata group", 20)]:
    ids = sorted(e0[(e0.role == "probe") & (e0.link == lt)].index)
    for g in rng.sample(ids, min(k, len(ids))):
        sel.append({"item": f"PM-{len(sel):03d}", "kind": f"probe_nearest_mate:{lt}", "a": g, "b": e0.nearest_mate[g]})
ctl = sorted(e0[e0.role == "control"].index)
for g in rng.sample(ctl, 30):
    sel.append({"item": f"CN-{len(sel):03d}", "kind": "control_nearest_C0_train", "a": g, "b": e0.nearest_C0[g]})
(S / "pm_items.json").write_text(json.dumps(sel, indent=1))
order = sel[:]; random.Random(99).shuffle(order)
codes = random.Random(100).sample(range(1000, 10000), len(order))
font = ImageFont.load_default(size=22); CELL = 380; PER = 6; key = {}
for s in range(0, len(order), PER):
    chunk = order[s:s + PER]
    sheet = Image.new("RGB", (2 * (2 * CELL + 30) + 20, 3 * (CELL + 40) + 10), "white"); dr = ImageDraw.Draw(sheet)
    for j, it in enumerate(chunk):
        code = f"P{codes[s + j]}"; key[code] = it["item"]
        col, row = j % 2, j // 2; ox, oy = 10 + col * (2 * CELL + 40), 10 + row * (CELL + 40)
        dr.text((ox, oy), code, fill=(200, 0, 0), font=font)
        for k, g in enumerate((it["a"], it["b"])):
            im = Image.open(REL / items.file_name[g]).convert("RGB"); im.thumbnail((CELL, CELL))
            if max(im.size) < CELL:
                sc = CELL / max(im.size); im = im.resize((int(im.width * sc), int(im.height * sc)), Image.NEAREST)
            sheet.paste(im, (ox + k * (CELL + 8), oy + 30))
    sheet.save(S / f"P_{s // PER:02d}.jpg", quality=90)
(S / "key_P.json").write_text(json.dumps(key, indent=1))
print("probe-mate sheets", (len(order) + PER - 1) // PER)
