# Provenance copy of an analysis script from the 2026-10-03 independent review. Local paths are redacted
# (<REPO>, <SCRATCH>, <LOCAL>); the maintained, runnable versions are in reports/m7_final/scripts/.
"""Phase 3: verify the controlled design from manifests and packages."""
import hashlib, json, zipfile
from pathlib import Path
import numpy as np
import pandas as pd

REPO = Path("<REPO>")
EXP = Path("C:/data/openinspect/exports/v0.1")
items = pd.read_parquet(REPO / "manifests/releases/v0.1/items.parquet").set_index("global_id")
ann = pd.read_parquet(REPO / "manifests/releases/v0.1/annotations.parquet")
ann["w"] = ann.x_max - ann.x_min; ann["h"] = ann.y_max - ann.y_min
ann = ann.join(items[["width", "height"]], on="global_id")
ann["rel_area"] = ann.w * ann.h / (ann.width * ann.height)
out = {}


def pkg_hashes(name, split):
    with zipfile.ZipFile(EXP / f"openinspect-trust-v0.1-{name}-yolo.zip") as z:
        return {n.split("/")[-1].rsplit(".", 1)[0] + ("#lbl" if n.startswith("labels") else ""): hashlib.sha256(z.read(n)).hexdigest()
                for n in z.namelist() if n.startswith((f"images/{split}/", f"labels/{split}/"))}


def profile(ids):
    it = items.loc[list(ids)]; a = ann[ann.global_id.isin(ids)]
    return {"n": len(it), "source": it.source.value_counts().to_dict(), "boxes": int(it.boxes.sum()),
            "boxes_per_img": round(float(it.boxes.mean()), 3),
            "class_boxes": a.normalized_label.value_counts().to_dict(),
            "median_wh": [float(it.width.median()), float(it.height.median())],
            "ext": it.file_name.str.rsplit(".", n=1).str[-1].value_counts().to_dict(),
            "median_rel_box_area": float(a.rel_area.median()), "mean_rel_box_area": float(a.rel_area.mean())}


for d in range(3):
    r = pd.read_csv(REPO / f"manifests/experiments/v0.1/C-design{d}-roles.csv").set_index("id")
    c0 = pd.read_csv(REPO / f"manifests/experiments/v0.1/C0__design{d}.csv").set_index("id").split
    c1 = pd.read_csv(REPO / f"manifests/experiments/v0.1/C1__design{d}.csv").set_index("id").split
    res = {}
    for s in ["train", "val", "test"]:
        a, b = set(c0[c0 == s].index), set(c1[c1 == s].index)
        res[f"{s}_C0"] = len(a); res[f"{s}_C1"] = len(b); res[f"{s}_only_C0"] = len(a - b); res[f"{s}_only_C1"] = len(b - a)
    tr0, tr1 = set(c0[c0 == "train"].index), set(c1[c1 == "train"].index)
    mates, repl = set(r[r.role == "mate"].index), set(r[r.role == "replacement"].index)
    res["C0_minus_C1_train_equals_mates"] = (tr0 - tr1) == mates
    res["C1_minus_C0_train_equals_replacements"] = (tr1 - tr0) == repl
    probes, controls = set(r[r.role == "probe"].index), set(r[r.role == "control"].index)
    res["test_equals_probes_plus_controls"] = set(c0[c0 == "test"].index) == probes | controls
    # package-level hash identity
    for s in ["test", "val"]:
        h0, h1 = pkg_hashes(f"C0-d{d}", s), pkg_hashes(f"C1-d{d}", s)
        res[f"pkg_{s}_files_identical_sha256"] = h0 == h1
        res[f"pkg_{s}_n_files"] = len(h0)
    h0, h1 = pkg_hashes(f"C0-d{d}", "train"), pkg_hashes(f"C1-d{d}", "train")
    only0 = {k.split("#")[0] for k in set(h0) - set(h1)}; only1 = {k.split("#")[0] for k in set(h1) - set(h0)}
    res["pkg_train_diff_C0_is_mates"] = only0 == mates; res["pkg_train_diff_C1_is_replacements"] = only1 == repl
    res["pkg_train_common_identical"] = all(h0[k] == h1[k] for k in set(h0) & set(h1))
    # package image bytes vs release sha256
    with zipfile.ZipFile(EXP / f"openinspect-trust-v0.1-C0-d{d}-yolo.zip") as z:
        bad = sum(hashlib.sha256(z.read(n)).hexdigest() != items.loc[n.split("/")[-1].rsplit(".", 1)[0], "sha256"]
                  for n in z.namelist() if n.startswith("images/test/"))
    res["pkg_test_images_match_release_sha256_mismatches"] = int(bad)
    # exposure via A1 constraint group
    cg = items.constraint_group
    grp_tr0 = set(cg.loc[list(tr0)]); grp_tr1 = set(cg.loc[list(tr1)])
    res["probes_with_constraint_group_in_C0_train"] = int(sum(cg[p] in grp_tr0 for p in probes))
    res["probes_with_constraint_group_in_C1_train"] = int(sum(cg[p] in grp_tr1 for p in probes))
    res["controls_with_constraint_group_in_C0_train"] = int(sum(cg[p] in grp_tr0 for p in controls))
    res["controls_with_constraint_group_in_C1_train"] = int(sum(cg[p] in grp_tr1 for p in controls))
    # exposure_group membership of mates
    eg = r.exposure_group
    res["probes_whose_exposure_group_has_C0_train_mate"] = int(sum(((eg == eg[p]) & r.index.isin(list(tr0)) & (r.role == "mate")).any() for p in probes))
    res["control_group_sizes"] = cg.loc[list(controls)].map(cg.value_counts()).value_counts().sort_index().to_dict()
    res["probe_group_sizes"] = cg.loc[list(probes)].map(cg.value_counts()).describe().round(2).to_dict()
    res["profile_mates"] = profile(mates); res["profile_replacements"] = profile(repl)
    res["profile_probes"] = profile(probes); res["profile_controls"] = profile(controls)
    res["replacements_whose_group_touches_test_or_val"] = int(sum(
        any(c0.get(x) in ("test", "val") for x in cg[cg == cg[i]].index) for i in repl))
    out[f"design{d}"] = res

json.dump(out, open("design_check.json", "w"), indent=1, default=str)
for d, res in out.items():
    print("==", d)
    for k, v in res.items():
        if not k.startswith("profile"):
            print(f"  {k}: {v}")
    for k in ["profile_mates", "profile_replacements", "profile_probes", "profile_controls"]:
        print(f"  {k}: {res[k]}")
