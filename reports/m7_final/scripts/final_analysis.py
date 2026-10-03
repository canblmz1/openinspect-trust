"""M7 final analysis: replication table, seed-aware uncertainty, placebo, dose-response, visual categories.

Reads per-image detections from $OPENINSPECT_DATA_DIR/m7/eval/<model>.parquet (written by the M7
evaluator, Ultralytics 8.3.0, imgsz 640, conf 0.001, iou 0.7, max_det 300). Discovers which matched
C0/C1 seed pairs exist; adds new seeds automatically. Nothing here trains or calls EVREN.

Pre-registered choices (fixed before any new-seed result was seen, 2026-10-03):
- primary estimand: D0 probe mAP50-95 (C0) - (C1), mean across seeds; overall D0 secondary;
- D1 seed 1 C0 member = first-created replicate of C0-d1-s1 (alias r1); the second replicate (r2) = sensitivity;
- dose-response bins: exposure delta (max cos to C0 train - max cos to C1 train) < 0.02 / 0.02-0.08 / > 0.08;
- bootstrap unit: A1 constraint group; 2000 draws; placebo 10,000 source-stratified cluster draws.
"""
import json, sys, time
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats as st

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent))
from lib import Model, REPO, EVAL  # own COCO-101 AP; verified identical to Ultralytics val (0.0000 pp)

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parents[1]
OUT.mkdir(parents=True, exist_ok=True)
B = 2000
NPERM = int(sys.argv[2]) if len(sys.argv) > 2 else 10000
rng = np.random.default_rng(20261003)
items = pd.read_parquet(REPO / "manifests/releases/v0.1/items.parquet").set_index("global_id")
ROLES = {d: pd.read_csv(REPO / f"manifests/experiments/v0.1/C-design{d}-roles.csv").set_index("id") for d in range(3)}
C0_ALIAS = {(1, 1): "C0-d1-s1-r1"}  # pre-registered: first-created replicate
SENSITIVITY = {(1, 1): "C0-d1-s1-r2"}


def exists(name):
    return (EVAL / f"{name}.parquet").exists()


def pairs_for(d):
    out = []
    for s in range(10):
        c0 = C0_ALIAS.get((d, s), f"C0-d{d}-s{s}")
        c1 = f"C1-d{d}-s{s}"
        if exists(c0) and exists(c1):
            out.append((s, c0, c1))
    return out


PAIRS = {d: pairs_for(d) for d in range(3)}
M = {}


def model(n):
    if n not in M:
        M[n] = Model(n)
    return M[n]


def masks(d, m):
    role = ROLES[d].role.reindex(m.images)
    return {"overall": np.ones(len(m.images)), "probe": (role == "probe").values.astype(float),
            "control": (role == "control").values.astype(float)}


def contrast(d, c0, c1, w=None):
    a, b = model(c0), model(c1)
    assert a.images == b.images, "C0/C1 image order differs"
    S = masks(d, a)
    w = np.ones(len(a.images)) if w is None else w
    r = {k: 100 * (a.map(w * v) - b.map(w * v)) for k, v in S.items()}
    r["probe_minus_control"] = r["probe"] - r["control"]
    return r


# ------------------------------------------------------------------ 1. replication table
rows = []
for d, ps in PAIRS.items():
    for s, c0, c1 in ps:
        r = contrast(d, c0, c1)
        rows.append({"design": f"D{d}", "seed": s, "C0_model": c0, "C1_model": c1, **{k: round(v, 6) for k, v in r.items()},
                     "C0_overall_mAP50_95": round(100 * model(c0).map(np.ones(len(model(c0).images))), 6),
                     "C1_overall_mAP50_95": round(100 * model(c1).map(np.ones(len(model(c1).images))), 6)})
for (d, s), alt in SENSITIVITY.items():
    if exists(alt) and exists(f"C1-d{d}-s{s}"):
        r = contrast(d, alt, f"C1-d{d}-s{s}")
        rows.append({"design": f"D{d}", "seed": f"{s} (sensitivity: other replicate)", "C0_model": alt, "C1_model": f"C1-d{d}-s{s}",
                     **{k: round(v, 6) for k, v in r.items()}})
rep = pd.DataFrame(rows)
summ = []
for d in range(3):
    x = rep[(rep.design == f"D{d}") & rep.seed.apply(lambda v: isinstance(v, (int, np.integer)))]
    for k in ["overall", "probe", "control", "probe_minus_control"]:
        v = x[k].astype(float)
        summ.append({"design": f"D{d}", "estimand": k, "n_seeds": len(v), "mean": v.mean(), "sd": v.std(ddof=1) if len(v) > 1 else np.nan,
                     "median": v.median(), "min": v.min(), "max": v.max(), "per_seed": list(v.round(4))})
summ = pd.DataFrame(summ)
rep.to_csv(OUT / "FINAL_REPLICATION_TABLE.csv", index=False)
summ.to_csv(OUT / "replication_summary.csv", index=False)
print(rep.to_string()); print(summ.round(3).to_string())

# ------------------------------------------------------------------ 2. seed-aware uncertainty
def group_index(d):
    imgs = model(PAIRS[d][0][1]).images
    cg = items.constraint_group.reindex(imgs).values
    u, inv = np.unique(cg, return_inverse=True)
    return u, inv


def boot(d):
    ps = PAIRS[d]; u, inv = group_index(d); k = len(ps)
    point = [contrast(d, c0, c1) for _, c0, c1 in ps]
    keys = ["overall", "probe", "control", "probe_minus_control"]
    A, C = [], []
    for _ in range(B):
        w = np.bincount(rng.integers(0, len(u), len(u)), minlength=len(u))[inv].astype(float)
        per = [contrast(d, c0, c1, w) for _, c0, c1 in ps]
        A.append([np.mean([p[q] for p in per]) for q in keys])
        sel = rng.integers(0, k, k)  # resample seeds (two-stage)
        C.append([np.mean([per[i][q] for i in sel]) for q in keys])
    A, C = np.array(A), np.array(C)
    res = []
    for j, q in enumerate(keys):
        v = np.array([p[q] for p in point]); m = v.mean()
        row = {"design": f"D{d}", "estimand": q, "n_seeds": k, "point_mean": m,
               "A_test_sampling_lo": np.percentile(A[:, j], 2.5), "A_test_sampling_hi": np.percentile(A[:, j], 97.5),
               "C_combined_two_stage_lo": np.percentile(C[:, j], 2.5), "C_combined_two_stage_hi": np.percentile(C[:, j], 97.5),
               "C_combined_P_le_0": float((C[:, j] <= 0).mean())}
        if k > 1:
            h = st.t.ppf(0.975, k - 1) * v.std(ddof=1) / np.sqrt(k)
            row.update({"B_seed_sd": v.std(ddof=1), "B_seed_t_lo": m - h, "B_seed_t_hi": m + h})
        res.append(row)
    return res


t0 = time.time()
sa = pd.DataFrame([r for d in range(3) for r in boot(d)])
# pooled across designs (each design one estimate, inverse-variance on combined two-stage variance)
pool = []
for q in ["probe", "probe_minus_control", "overall"]:
    x = sa[sa.estimand == q]
    var = ((x.C_combined_two_stage_hi - x.C_combined_two_stage_lo) / 3.92) ** 2
    w = 1 / var; m = (w * x.point_mean).sum() / w.sum(); se = 1 / np.sqrt(w.sum())
    pool.append({"design": "pooled D0+D1+D2 (inverse-variance)", "estimand": q, "point_mean": m,
                 "C_combined_two_stage_lo": m - 1.96 * se, "C_combined_two_stage_hi": m + 1.96 * se})
sa = pd.concat([sa, pd.DataFrame(pool)])
sa.to_csv(OUT / "FINAL_SEED_AWARE_STATS.csv", index=False)
print(sa.round(3).to_string()); print("bootstrap s", round(time.time() - t0))

# ------------------------------------------------------------------ 3. placebo
def placebo(d):
    ps = PAIRS[d]; m0 = model(ps[0][1]); im = m0.images; r = ROLES[d].role.reindex(im).values
    cg = items.constraint_group.reindex(im).values; src = items.source.astype(str).reindex(im).values
    groups = pd.Series(np.arange(len(im))).groupby(cg).apply(list).tolist()
    by_src = {s: [g for g in groups if src[g[0]] == s] for s in np.unique(src)}
    target = {s: int(((r == "probe") & (src == s)).sum()) for s in by_src}
    obs = np.mean([contrast(d, c0, c1)["probe_minus_control"] for _, c0, c1 in ps])
    prng = np.random.default_rng(1000 + d); vals = np.empty(NPERM)
    for i in range(NPERM):
        P = np.zeros(len(im))
        for s, gs in by_src.items():
            tot = 0
            for o in prng.permutation(len(gs)):
                if tot >= target[s]: break
                P[gs[o]] = 1; tot += len(gs[o])
        C = 1 - P
        vals[i] = np.mean([(100 * (model(c0).map(P) - model(c1).map(P))) - (100 * (model(c0).map(C) - model(c1).map(C))) for _, c0, c1 in ps])
    return {"design": f"D{d}", "n_seeds": len(ps), "observed_probe_minus_control": obs, "null_mean": vals.mean(), "null_sd": vals.std(),
            "null_q025": np.percentile(vals, 2.5), "null_q975": np.percentile(vals, 97.5), "n_permutations": NPERM,
            "p_one_sided": ((vals >= obs).sum() + 1) / (NPERM + 1), "p_two_sided": ((np.abs(vals) >= abs(obs)).sum() + 1) / (NPERM + 1)}, vals


t0 = time.time(); pl = []
for d in range(3):
    res, vals = placebo(d); pl.append(res); np.save(OUT / f"placebo_null_D{d}.npy", vals)
pd.DataFrame(pl).to_csv(OUT / "FINAL_PLACEBO_RESULTS.csv", index=False)
print(pd.DataFrame(pl).round(4).to_string()); print("placebo s", round(time.time() - t0))

# ------------------------------------------------------------------ 4. dose-response
ex = pd.read_csv(REPO / "reports/m7_independent_review/data/exposure.csv")  # frozen similarity, computed before this phase
dr = []
for d, ps in PAIRS.items():
    for rep_ in ["small", "base"]:
        e = ex[(ex.design == d) & (ex.rep == rep_)].set_index("id")
        bins = {"control": e.role == "control", "probe delta<0.02": (e.role == "probe") & (e.delta < 0.02),
                "probe 0.02-0.08": (e.role == "probe") & e.delta.between(0.02, 0.08), "probe delta>0.08": (e.role == "probe") & (e.delta > 0.08)}
        for k, sel in bins.items():
            ids = e.index[sel]; per = []
            for s, c0, c1 in ps:
                a, b = model(c0), model(c1); per.append(100 * (a.map(a.mask(ids)) - b.map(b.mask(ids))))
            dr.append({"design": f"D{d}", "representation": f"DINOv2-{rep_}", "bin": k, "n_images": int(sel.sum()), "n_seeds": len(ps),
                       "per_seed": [round(v, 4) for v in per], "mean": np.mean(per), "sd": np.std(per, ddof=1) if len(per) > 1 else np.nan})
drd = pd.DataFrame(dr)
# continuous: per-image recall gain (mean over seeds) vs delta, Spearman with cluster bootstrap CI; probes only
cont = []
for d, ps in PAIRS.items():
    gains = []
    for s, c0, c1 in ps:
        g = model(c0).per_image_recall(0.25).recall5095 - model(c1).per_image_recall(0.25).recall5095
        gains.append(g)
    for rep_ in ["small", "base"]:
        e = ex[(ex.design == d) & (ex.rep == rep_)].set_index("id")
        pr = e[e.role == "probe"].index
        g = pd.concat(gains, axis=1).reindex(pr)
        x = e.delta.reindex(pr).values; y = g.mean(axis=1).values
        rho = st.spearmanr(x, y).statistic
        cg = items.constraint_group.reindex(pr).values; u, inv = np.unique(cg, return_inverse=True); bs = []
        for _ in range(B):
            idx = np.concatenate([np.where(inv == j)[0] for j in rng.integers(0, len(u), len(u))])
            bs.append(st.spearmanr(x[idx], y[idx]).statistic)
        per_seed = [round(st.spearmanr(x, g.iloc[:, i].values).statistic, 3) for i in range(g.shape[1])]
        cont.append({"design": f"D{d}", "representation": f"DINOv2-{rep_}", "bin": "continuous: Spearman(delta, per-image recall gain), probes",
                     "n_images": len(pr), "n_seeds": len(ps), "mean": rho, "ci_lo": np.nanpercentile(bs, 2.5), "ci_hi": np.nanpercentile(bs, 97.5), "per_seed": per_seed})
drd = pd.concat([drd, pd.DataFrame(cont)])
drd.to_csv(OUT / "FINAL_DOSE_RESPONSE.csv", index=False)
print(drd.round(3).to_string())

# ------------------------------------------------------------------ 5. coarse visual categories (frozen AI adjudication; D0 sample)
v = pd.read_csv(REPO / "reports/m7_independent_review/AI_PM_ADJUDICATED.csv", index_col=0)
v = v[v.pair_role.str.startswith("probe")]
COARSE = {"A": "same-instance-like", "B": "same-instance-like", "C": "same-family-like", "D": "structurally related",
          "E": "unrelated", "F": "unrelated", "G": "ambiguous"}
v["coarse"] = v.final_category.map(COARSE)
vc = []
for c in ["same-instance-like", "same-family-like", "structurally related", "unrelated", "ambiguous"]:
    ids = v[v.coarse == c].probe_id.tolist(); per = []
    for s, c0, c1 in PAIRS[0]:
        a, b = model(c0), model(c1); per.append(100 * (a.map(a.mask(ids)) - b.map(b.mask(ids))))
    nb = int(model(PAIRS[0][0][1]).mask(ids)[model(PAIRS[0][0][1]).t_img].sum())
    vc.append({"coarse_category": c, "n_probes": len(ids), "n_boxes": nb, "per_seed": [round(x, 2) for x in per], "mean": np.mean(per)})
pd.DataFrame(vc).to_csv(OUT / "visual_category_gain_D0.csv", index=False)
print(pd.DataFrame(vc).round(2).to_string())
json.dump({"pairs": {f"D{d}": [list(p) for p in ps] for d, ps in PAIRS.items()}, "B": B, "NPERM": NPERM}, open(OUT / "analysis_meta.json", "w"), indent=1, default=str)
print("DONE")
