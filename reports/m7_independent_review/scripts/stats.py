"""Phases 9-12: statistical red-team, placebo tests, confounders, D1 investigation."""
import json, sys, time
from itertools import product
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).parent))
from lib import Model, REPO

t0 = time.time()
items = pd.read_parquet(REPO / "manifests/releases/v0.1/items.parquet").set_index("global_id")
ann = pd.read_parquet(REPO / "manifests/releases/v0.1/annotations.parquet")
ann["area"] = (ann.x_max - ann.x_min) * (ann.y_max - ann.y_min)
ann = ann.join(items[["width", "height"]], on="global_id"); ann["rel_area"] = ann.area / (ann.width * ann.height)
R = {d: pd.read_csv(REPO / f"manifests/experiments/v0.1/C-design{d}-roles.csv").set_index("id") for d in range(3)}
M = {n: Model(n) for n in ["C0-d0-s0", "C0-d0-s1", "C0-d0-s2", "C1-d0-s0", "C1-d0-s1", "C1-d0-s2", "C0-d1-s0", "C1-d1-s0",
                            "C0-d2-s0", "C1-d2-s0", "noise__C1-d0-s0__r1", "noise__C0-d1-s1__r2", "noise__C0-d1-s1__r1"]}
REP = {}


def subset_masks(d, model):
    r = R[d]; imgs = model.images
    role = r.role.reindex(imgs)
    return {"overall": np.ones(len(imgs)), "probe": (role == "probe").values.astype(float), "control": (role == "control").values.astype(float)}


def mp(model, w):
    return 100 * model.map(w)


# ---------- 1. point estimates ----------
pe = {}
pairs = {0: [("C0-d0-s0", "C1-d0-s0"), ("C0-d0-s1", "C1-d0-s1"), ("C0-d0-s2", "C1-d0-s2")], 1: [("C0-d1-s0", "C1-d1-s0")], 2: [("C0-d2-s0", "C1-d2-s0")]}
for d, ps in pairs.items():
    for a, b in ps:
        S = subset_masks(d, M[a])
        pe[f"{a}|{b}"] = {k: mp(M[a], w) - mp(M[b], w) for k, w in S.items()}
        pe[f"{a}|{b}"]["did"] = pe[f"{a}|{b}"]["probe"] - pe[f"{a}|{b}"]["control"]
REP["point_estimates"] = pe
d0 = [pe[f"{a}|{b}"] for a, b in pairs[0]]
REP["d0_mean"] = {k: float(np.mean([x[k] for x in d0])) for k in d0[0]}
print("point estimates", json.dumps(REP["d0_mean"], indent=0))

# ---------- 2. training-noise null for subset contrasts ----------
# every pair of models trained on the SAME condition (D0 population): C0 si vs sj, C1 si vs sj, C1-s0 vs its replicate
S0 = subset_masks(0, M["C0-d0-s0"])
null_pairs = [("C0-d0-s0", "C0-d0-s1"), ("C0-d0-s0", "C0-d0-s2"), ("C0-d0-s1", "C0-d0-s2"),
              ("C1-d0-s0", "C1-d0-s1"), ("C1-d0-s0", "C1-d0-s2"), ("C1-d0-s1", "C1-d0-s2"),
              ("C1-d0-s0", "noise__C1-d0-s0__r1"), ("C1-d0-s1", "noise__C1-d0-s0__r1"), ("C1-d0-s2", "noise__C1-d0-s0__r1")]
cache = {(n, k): mp(M[n], w) for n in [x for p in null_pairs for x in p] + [p for q in pairs[0] for p in q] for k, w in S0.items()}
nullc = []
for a, b in null_pairs:
    e = {k: cache[(a, k)] - cache[(b, k)] for k in S0}; e["did"] = e["probe"] - e["control"]; e["pair"] = f"{a} - {b}"; nullc.append(e)
cross = []
for a in ["C0-d0-s0", "C0-d0-s1", "C0-d0-s2"]:
    for b in ["C1-d0-s0", "C1-d0-s1", "C1-d0-s2", "noise__C1-d0-s0__r1"]:
        e = {k: cache[(a, k)] - cache[(b, k)] for k in S0}; e["did"] = e["probe"] - e["control"]; e["pair"] = f"{a} - {b}"; cross.append(e)
nd, cd = pd.DataFrame(nullc), pd.DataFrame(cross)
REP["same_condition_null_pairs"] = nd.to_dict(orient="records"); REP["cross_condition_pairs"] = cd.to_dict(orient="records")
# null SD of single-pair contrasts (sign is arbitrary -> use RMS)
REP["same_condition_rms"] = {k: float(np.sqrt((nd[k] ** 2).mean())) for k in ["overall", "probe", "control", "did"]}
REP["cross_condition_mean"] = {k: float(cd[k].mean()) for k in ["overall", "probe", "control", "did"]}
REP["cross_condition_min"] = {k: float(cd[k].min()) for k in ["overall", "probe", "control", "did"]}
print("same-condition RMS", REP["same_condition_rms"]); print("cross mean", REP["cross_condition_mean"], "min", REP["cross_condition_min"])
# D1 replicate pair on D1 population (both C0-d1-s1)
S1 = subset_masks(1, M["C0-d1-s0"])
a, b = "noise__C0-d1-s1__r2", "noise__C0-d1-s1__r1"
REP["d1_replicate_pair"] = {k: mp(M[a], w) - mp(M[b], w) for k, w in S1.items()}
REP["d1_C0s0_vs_C0s1reps"] = {f"C0-d1-s0 - {x}": {k: mp(M["C0-d1-s0"], w) - mp(M[x], w) for k, w in S1.items()} for x in (a, b)}
REP["d1_C0s1reps_vs_C1s0"] = {f"{x} - C1-d1-s0": {k: mp(M[x], w) - mp(M["C1-d1-s0"], w) for k, w in S1.items()} for x in (a, b)}
print("D1 replicate pair", REP["d1_replicate_pair"]); print(REP["d1_C0s1reps_vs_C1s0"])

# ---------- 3. bootstrap variants for D0 ----------
imgs = M["C0-d0-s0"].images
cg = items.constraint_group.reindex(imgs).values
ucg, inv = np.unique(cg, return_inverse=True)
P, C = S0["probe"], S0["control"]
rng = np.random.default_rng(12345)
B = 1000
names0 = [p for q in pairs[0] for p in q]


def contrasts(w, models):
    v = {n: (mp(M[n], w * P), mp(M[n], w * C), mp(M[n], w)) for n in set(models)}
    return v


boot = {"cluster_same_resample": [], "hierarchical_seed_and_cluster": [], "iid_image": []}
for it in range(B):
    cnt = np.bincount(rng.integers(0, len(ucg), len(ucg)), minlength=len(ucg))
    w = cnt[inv].astype(float)
    v = contrasts(w, names0)
    dd = [(v[a][0] - v[b][0], v[a][1] - v[b][1], v[a][2] - v[b][2]) for a, b in pairs[0]]
    boot["cluster_same_resample"].append(np.mean(dd, axis=0))
    s = rng.integers(0, 3, 3)
    boot["hierarchical_seed_and_cluster"].append(np.mean([dd[i] for i in s], axis=0))
    wi = np.bincount(rng.integers(0, len(imgs), len(imgs)), minlength=len(imgs)).astype(float)
    v = contrasts(wi, names0)
    boot["iid_image"].append(np.mean([(v[a][0] - v[b][0], v[a][1] - v[b][1], v[a][2] - v[b][2]) for a, b in pairs[0]], axis=0))
ci = {}
for k, arr in boot.items():
    arr = np.array(arr)  # probe, control, overall
    did = arr[:, 0] - arr[:, 1]
    ci[k] = {"probe": np.percentile(arr[:, 0], [2.5, 97.5]).tolist(), "control": np.percentile(arr[:, 1], [2.5, 97.5]).tolist(),
             "overall": np.percentile(arr[:, 2], [2.5, 97.5]).tolist(), "did": np.percentile(did, [2.5, 97.5]).tolist(),
             "p_did_le_0": float((did <= 0).mean()), "p_probe_le_0": float((arr[:, 0] <= 0).mean()), "p_overall_le_0": float((arr[:, 2] <= 0).mean())}
# training-noise inflation: add N(0, sd) per-seed noise to each seed's contrast, sd from same-condition pairs / sqrt(2)? Each C0-C1 pair difference
# has training variance 2*sigma^2 where sigma^2 = var of a single model; same-condition pair RMS^2 = 2 sigma^2 => pair noise sd = RMS.
arr = np.array(boot["cluster_same_resample"])
noise_sd = {"probe": REP["same_condition_rms"]["probe"], "control": REP["same_condition_rms"]["control"], "overall": REP["same_condition_rms"]["overall"]}
# note: the same-condition RMS already contains test-sampling-free training variation on the fixed test set
nz = rng.normal(0, 1, (B, 3, 3)) * np.array([noise_sd["probe"], noise_sd["control"], noise_sd["overall"]])
arr_n = arr + nz.mean(1)
didn = arr_n[:, 0] - arr_n[:, 1]
ci["cluster_plus_training_noise"] = {"probe": np.percentile(arr_n[:, 0], [2.5, 97.5]).tolist(), "control": np.percentile(arr_n[:, 1], [2.5, 97.5]).tolist(),
                                     "overall": np.percentile(arr_n[:, 2], [2.5, 97.5]).tolist(), "did": np.percentile(didn, [2.5, 97.5]).tolist(),
                                     "p_did_le_0": float((didn <= 0).mean()), "p_probe_le_0": float((arr_n[:, 0] <= 0).mean()), "p_overall_le_0": float((arr_n[:, 2] <= 0).mean()),
                                     "noise_sd_used": noise_sd}
# seed-only t interval
from scipy import stats as st
for k in ["overall", "probe", "control", "did"]:
    x = np.array([e[k] for e in d0]); h = st.t.ppf(0.975, 2) * x.std(ddof=1) / np.sqrt(3)
    ci.setdefault("seed_only_t2", {})[k] = [float(x.mean() - h), float(x.mean() + h)]
REP["d0_intervals"] = ci
print(json.dumps(ci, indent=1))

# ---------- 4. placebo: random fake probe/control labels ----------
def placebo(d, mpairs, nperm, stratify):
    model0 = M[mpairs[0][0]]; im = model0.images; r = R[d].role.reindex(im)
    test_cg = items.constraint_group.reindex(im).values; src = items.source.reindex(im).values
    nP = int((r == "probe").sum())
    # per-model per-cluster cached? mAP is not additive: recompute each time
    obs = np.mean([mp(M[a], subset_masks(d, model0)["probe"]) - mp(M[b], subset_masks(d, model0)["probe"])
                   - (mp(M[a], subset_masks(d, model0)["control"]) - mp(M[b], subset_masks(d, model0)["control"])) for a, b in mpairs])
    groups = pd.Series(np.arange(len(im))).groupby(test_cg).apply(list).tolist()
    rngp = np.random.default_rng(777 + d)
    vals = []
    for _ in range(nperm):
        if stratify:
            fakeP = np.zeros(len(im))
            for s in np.unique(src):
                gs = [g for g in groups if src[g[0]] == s]
                target = int(((r == "probe") & (src == s)).sum())
                order = rngp.permutation(len(gs)); tot = 0
                for o in order:
                    if tot >= target: break
                    fakeP[gs[o]] = 1; tot += len(gs[o])
        else:
            fakeP = np.zeros(len(im)); order = rngp.permutation(len(groups)); tot = 0
            for o in order:
                if tot >= nP: break
                fakeP[groups[o]] = 1; tot += len(groups[o])
        fakeC = 1 - fakeP
        vals.append(np.mean([(mp(M[a], fakeP) - mp(M[b], fakeP)) - (mp(M[a], fakeC) - mp(M[b], fakeC)) for a, b in mpairs]))
    vals = np.array(vals)
    return {"observed_did": float(obs), "null_mean": float(vals.mean()), "null_sd": float(vals.std()),
            "null_q": np.percentile(vals, [2.5, 50, 97.5]).tolist(), "p_one_sided": float(((vals >= obs).sum() + 1) / (len(vals) + 1)),
            "p_two_sided_abs": float(((np.abs(vals) >= abs(obs)).sum() + 1) / (len(vals) + 1)), "n": len(vals)}, vals


pl = {}
pl["d0_cluster_random"], v0 = placebo(0, pairs[0], 2000, False)
pl["d0_cluster_source_stratified"], v0s = placebo(0, pairs[0], 2000, True)
pl["d1_cluster_source_stratified"], v1s = placebo(1, pairs[1], 2000, True)
pl["d2_cluster_source_stratified"], v2s = placebo(2, pairs[2], 2000, True)
REP["placebo"] = pl
np.save("placebo_d0.npy", v0s)
print(json.dumps(pl, indent=1))

# ---------- 5. decomposition by probe link type, source, class ----------
dec = []
for d, ps in pairs.items():
    model0 = M[ps[0][0]]; im = model0.images; r = R[d].reindex(im)
    sub = {}
    for lt in ["crop sibling", "similar pair", "same component", "same metadata group"]:
        sub[f"probe:{lt}"] = ((r.role == "probe") & (r.probe_link == lt)).values.astype(float)
    for s in ["dspcbsd-plus", "pcb-defect", "pcb-ind"]:
        sub[f"probe:{s}"] = ((r.role == "probe") & (r.source == s)).values.astype(float)
        sub[f"control:{s}"] = ((r.role == "control") & (r.source == s)).values.astype(float)
    sub["control:singleton"] = ((r.role == "control") & (items.constraint_group.reindex(im).map(items.constraint_group.value_counts()) == 1).values).values.astype(float)
    sub["control:grouped"] = ((r.role == "control") & (items.constraint_group.reindex(im).map(items.constraint_group.value_counts()) > 1).values).values.astype(float)
    for k, w in sub.items():
        vals = [mp(M[a], w) - mp(M[b], w) for a, b in ps]
        dec.append({"design": d, "subset": k, "n_images": int(w.sum()), "n_boxes": int(w[M[ps[0][0]].t_img].sum()),
                    "per_seed": [round(x, 2) for x in vals], "mean": float(np.mean(vals))})
REP["decomposition"] = dec
print(pd.DataFrame(dec).to_string())

# ---------- 6. per-class contrasts on probes/controls ----------
pcl = []
for d, ps in pairs.items():
    S = subset_masks(d, M[ps[0][0]])
    for part in ["probe", "control"]:
        acc = {}
        for a, b in ps:
            ca, cb = M[a].map(S[part], per_class=True), M[b].map(S[part], per_class=True)
            for c in ca:
                acc.setdefault(c, []).append(100 * (ca[c] - cb[c]))
        for c, v in acc.items():
            pcl.append({"design": d, "part": part, "class": ["short", "open", "mouse_bite", "spurious_copper"][c], "mean": float(np.mean(v)), "per_seed": [round(x, 2) for x in v]})
REP["per_class"] = pcl
print(pd.DataFrame(pcl).to_string())
json.dump(REP, open("stats.json", "w"), indent=1, default=float)
print("done", time.time() - t0)
