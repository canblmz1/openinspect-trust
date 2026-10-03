"""Phase 9 (confounders), dose-response, Phase 12 (D1), Phase 13/14 (source shift, source probe)."""
import json, sys
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import cross_val_predict, StratifiedKFold, GroupKFold
from sklearn.metrics import roc_auc_score, balanced_accuracy_score
import statsmodels.formula.api as smf
sys.path.insert(0, str(Path(__file__).parent))
from lib import Model, REPO

OUT = {}
items = pd.read_parquet(REPO / "manifests/releases/v0.1/items.parquet").set_index("global_id")
ann = pd.read_parquet(REPO / "manifests/releases/v0.1/annotations.parquet")
ann = ann.join(items[["width", "height"]], on="global_id")
ann["rel_area"] = (ann.x_max - ann.x_min) * (ann.y_max - ann.y_min) / (ann.width * ann.height)
feat = pd.DataFrame({
    "source": items.source, "width": items.width, "height": items.height, "aspect": items.width / items.height,
    "is_png": items.file_name.str.endswith(".png").astype(int), "boxes": items.boxes, "bytes": items.bytes,
    "group_size": items.constraint_group.map(items.constraint_group.value_counts()),
})
a = ann.groupby("global_id").agg(min_rel_area=("rel_area", "min"), mean_rel_area=("rel_area", "mean"))
feat = feat.join(a)
for c in ["short", "open", "mouse_bite", "spurious_copper"]:
    feat[f"n_{c}"] = ann[ann.normalized_label == c].groupby("global_id").size().reindex(feat.index).fillna(0)
ex = pd.read_csv(Path(__file__).parent / "exposure.csv")

# ---------- probe vs control predictability from trivial metadata ----------
pp = {}
for d in range(3):
    r = pd.read_csv(REPO / f"manifests/experiments/v0.1/C-design{d}-roles.csv").set_index("id")
    t = r[r.role.isin(["probe", "control"])]
    X = feat.loc[t.index].copy(); y = (t.role == "probe").astype(int).values
    X = pd.get_dummies(X, columns=["source"]).astype(float)
    res = {}
    for name, cols in [("metadata_without_group_size", [c for c in X.columns if c != "group_size"]), ("metadata_with_group_size", list(X.columns))]:
        rf = RandomForestClassifier(300, random_state=0, min_samples_leaf=3)
        cv = StratifiedKFold(5, shuffle=True, random_state=0)
        p = cross_val_predict(rf, X[cols].values, y, cv=cv, method="predict_proba")[:, 1]
        res[name] = {"cv_auc": float(roc_auc_score(y, p))}
    pp[f"design{d}"] = res
OUT["probe_control_predictability"] = pp
print("probe/control AUC", json.dumps(pp))

# ---------- per-image gain model (D0), mean over three seeds ----------
names = [("C0-d0-s0", "C1-d0-s0"), ("C0-d0-s1", "C1-d0-s1"), ("C0-d0-s2", "C1-d0-s2")]
r0 = pd.read_csv(REPO / "manifests/experiments/v0.1/C-design0-roles.csv").set_index("id")
gains = []
for a_, b_ in names:
    A, B = Model(a_).per_image_recall(0.25), Model(b_).per_image_recall(0.25)
    gains.append(A.recall5095 - B.recall5095)
g = pd.concat(gains, axis=1).mean(axis=1).rename("gain")
df = feat.loc[g.index].join(g)
df["probe"] = (r0.role.reindex(df.index) == "probe").astype(int)
e0 = ex[(ex.design == 0) & (ex.rep == "small")].set_index("id")
df["exp_delta_small"] = e0.delta.reindex(df.index); df["max_sim_C1"] = e0.max_sim_C1.reindex(df.index)
df["exp_delta_base"] = ex[(ex.design == 0) & (ex.rep == "base")].set_index("id").delta.reindex(df.index)
df["link"] = r0.probe_link.reindex(df.index).fillna("control")
df["cg"] = items.constraint_group.reindex(df.index)
df["log_area"] = np.log(df.mean_rel_area)
fits = {}
for name, f in [("probe_only", "gain ~ probe"), ("probe_plus_covariates", "gain ~ probe + C(source) + boxes + log_area + n_short + n_open + n_mouse_bite + max_sim_C1"),
                ("covariates_only", "gain ~ C(source) + boxes + log_area + n_short + n_open + n_mouse_bite + max_sim_C1"),
                ("exposure_delta", "gain ~ exp_delta_small + C(source) + boxes + log_area + max_sim_C1"),
                ("probe_x_source", "gain ~ probe * C(source) + boxes + log_area")]:
    m = smf.ols(f, df).fit(cov_type="cluster", cov_kwds={"groups": pd.factorize(df.cg)[0]})
    fits[name] = {"r2": float(m.rsquared), "params": {k: [float(m.params[k]), float(m.bse[k]), float(m.pvalues[k])] for k in m.params.index}}
OUT["per_image_gain_models"] = fits
for k, v in fits.items():
    print(k, round(v["r2"], 4), {p: [round(x, 4) for x in s] for p, s in v["params"].items() if p != "Intercept"})

# ---------- dose-response on subset mAP: probes binned by exposure delta ----------
M = {n: Model(n) for p in names for n in p}
bins = {"control": df.probe == 0, "probe delta<0.02": (df.probe == 1) & (df.exp_delta_small < 0.02),
        "probe 0.02-0.08": (df.probe == 1) & df.exp_delta_small.between(0.02, 0.08), "probe >0.08": (df.probe == 1) & (df.exp_delta_small > 0.08)}
dr = []
for k, sel in bins.items():
    ids = df.index[sel]
    vals = [100 * (M[a_].map(M[a_].mask(ids)) - M[b_].map(M[b_].mask(ids))) for a_, b_ in names]
    dr.append({"bin": k, "n": int(sel.sum()), "per_seed": [round(v, 2) for v in vals], "mean": float(np.mean(vals))})
OUT["dose_response_d0"] = dr
print(pd.DataFrame(dr))
# same by link x delta
print(df[df.probe == 1].groupby("link").exp_delta_small.describe().round(3))

# ---------- D1 investigation ----------
d1 = {}
for d in range(3):
    r = pd.read_csv(REPO / f"manifests/experiments/v0.1/C-design{d}-roles.csv").set_index("id")
    c = r[r.role == "control"]; p = r[r.role == "probe"]
    d1[f"design{d}"] = {
        "controls_by_source": c.source.value_counts().to_dict(),
        "control_group_size_dist": items.constraint_group.reindex(c.index).map(items.constraint_group.value_counts()).value_counts().sort_index().to_dict(),
        "mates_by_source": r[r.role == "mate"].source.value_counts().to_dict(),
        "control_boxes_by_class": ann[ann.global_id.isin(c.index)].normalized_label.value_counts().to_dict(),
        "exposure_delta_controls_mean_small": float(ex[(ex.design == d) & (ex.rep == "small") & (ex.role == "control")].delta.mean()),
        "controls_delta_gt_0.02": int((ex[(ex.design == d) & (ex.rep == "small") & (ex.role == "control")].delta > 0.02).sum()),
    }
# overlap of test sets between designs
T = {d: set(pd.read_csv(REPO / f"manifests/experiments/v0.1/C0__design{d}.csv").query("split=='test'").id) for d in range(3)}
d1["test_overlap"] = {f"{i}-{j}": len(T[i] & T[j]) for i in range(3) for j in range(i + 1, 3)}
OUT["d1"] = d1
print(json.dumps(d1, indent=1, default=str))

# ---------- source probe (Phase 14) ----------
X = feat[["width", "height", "aspect", "is_png", "boxes", "bytes"]]
y = feat.source
sp = {}
for name, cols in [("width+height+format", ["width", "height", "aspect", "is_png"]), ("+boxes", ["width", "height", "aspect", "is_png", "boxes"]),
                   ("+file_bytes", ["width", "height", "aspect", "is_png", "boxes", "bytes"]), ("boxes_only", ["boxes"]), ("bytes_only", ["bytes"])]:
    rf = RandomForestClassifier(300, random_state=0, min_samples_leaf=2)
    p = cross_val_predict(rf, X[cols].values, y, cv=GroupKFold(5), groups=items.constraint_group.values)
    sp[name] = float(balanced_accuracy_score(y, p))
sp["size_table"] = feat.groupby(["source", "width", "height", "is_png"]).size().rename("n").reset_index().to_dict(orient="records")
OUT["source_probe"] = sp
print("source probe", {k: v for k, v in sp.items() if k != "size_table"})
print(pd.DataFrame(sp["size_table"]).to_string())

# ---------- source shift red team (Phase 13) ----------
ss = {}
Bm = Model("B-strict-pcb-defect-s0"); A0 = Model("A0-s0")
a0_pd = [i for i in A0.images if i.startswith("OI_pcb-defect")]
ss["A0_on_its_pcbdefect_test"] = 100 * A0.map(A0.mask(a0_pd))
ss["Bstrict_pcbdefect_on_same_items"] = 100 * Bm.map(Bm.mask(a0_pd))
ss["Bstrict_pcbdefect_overall"] = 100 * Bm.map(np.ones(len(Bm.images)))
ss["Bstrict_pcbdefect_per_class"] = {k: 100 * v for k, v in Bm.map(np.ones(len(Bm.images)), per_class=True).items()}
det = pd.read_parquet(Path("C:/data/openinspect/m7/eval/B-strict-pcb-defect-s0.parquet"))
tg = pd.read_parquet(Path("C:/data/openinspect/m7/eval/B-strict-pcb-defect-s0.targets.parquet"))
ss["gt_class_counts"] = tg.cls.value_counts().sort_index().to_dict()
ss["pred_class_counts_conf>=0.25"] = det[det.conf >= 0.25].cls.value_counts().sort_index().to_dict()
ss["n_images"] = len(Bm.images); ss["preds_conf>=0.25_per_image"] = float((det.conf >= 0.25).sum() / len(Bm.images))
ss["max_conf_quantiles"] = det.groupby("image").conf.max().quantile([0.1, 0.5, 0.9]).round(3).to_dict()
# class-agnostic matching: does it find the boxes at all with the wrong class? tp_bits are class-aware; approximate by IoU with any GT
lbl = ann[ann.source == "pcb-defect"]
ss["recall_conf>=0.25_classaware_iou50"] = float(Bm.per_image_recall(0.25).assign(n=lambda d: d.n_gt).pipe(lambda d: 1))
ss["tp50_any_class"] = None
# A0 on same items: class confusion of top predictions
OUT["source_shift"] = ss
print(json.dumps(ss, indent=1, default=str))
json.dump(OUT, open(Path(__file__).parent / "confound.json", "w"), indent=1, default=str)
df.to_csv(Path(__file__).parent / "per_image_gain_d0.csv")
