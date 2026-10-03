import json, sys
import numpy as np, pandas as pd
sys.path.insert(0, ".")
from lib import Model, REPO
re = json.load(open("reeval.json"))
fm = pd.read_csv(REPO / "reports/m7/final_metrics.csv")
rows = []
names = {"noise/C1-d0-s0__r1": "noise__C1-d0-s0__r1", "noise/C0-d1-s1__r2": "noise__C0-d1-s1__r2", "noise/C0-d1-s1__r1": "noise__C0-d1-s1__r1"}
for run, r in re.items():
    m = Model(names.get(run, run))
    mine = m.map(np.ones(len(m.images)))
    rep = fm[(fm.model == run.split("/")[-1]) & (fm.subset == "overall")]
    rows.append({"run": run, "package": r["package"], "n_test_files": r["test_files"] // 2, "ultralytics_val_reeval": r["mAP50_95"] * 100,
                 "own_AP_on_saved_detections": mine * 100,
                 "reported_final_metrics": rep.mAP50_95.iloc[0] * 100 if len(rep) else np.nan,
                 "test_digest": r["test_digest"][:16]})
d = pd.DataFrame(rows)
d["abs_diff_reeval_vs_reported"] = (d.ultralytics_val_reeval - d.reported_final_metrics).abs()
d["abs_diff_own_vs_reeval"] = (d.own_AP_on_saved_detections - d.ultralytics_val_reeval).abs()
pd.set_option("display.width", 250)
print(d.round(4).to_string(index=False))
d.to_csv("repro_table.csv", index=False)
print(fm.model.unique())
