"""Independent re-evaluation of the M7 checkpoints with plain Ultralytics val().

Deliberately does NOT import or copy scripts/m7_evaluate.py. Extracts each
package's test split, runs YOLO(pt).val(split='test') with the documented
settings and records the validator's own metrics.
"""
import hashlib
import json
import sys
import time
import zipfile
from pathlib import Path

from ultralytics import YOLO, settings

settings.update({"sync": False})

DATA = Path("C:/data/openinspect")
EXP = DATA / "exports/v0.1"
SCR = Path(sys.argv[1])
PK = SCR / "pkgs"
OUT = SCR / "reeval.json"

RUNS = {
    "C0-d0-s0": "C0-d0", "C0-d0-s1": "C0-d0", "C0-d0-s2": "C0-d0",
    "C1-d0-s0": "C1-d0", "C1-d0-s1": "C1-d0", "C1-d0-s2": "C1-d0",
    "C0-d1-s0": "C0-d1", "C1-d1-s0": "C1-d1",
    "C0-d2-s0": "C0-d2", "C1-d2-s0": "C1-d2",
    "noise/C1-d0-s0__r1": "C1-d0",
    "noise/C0-d1-s1__r2": "C0-d1",
    "noise/C0-d1-s1__r1": "C0-d1",
    "A0-s0": "A0", "A1-s0": "A1",
    "B-strict-dspcbsd-plus-s0": "B-dspcbsd-plus",
    "B-natural-dspcbsd-plus-s0": "B-natural-dspcbsd-plus",
    "B-strict-pcb-ind-s0": "B-pcb-ind",
    "B-natural-pcb-ind-s0": "B-natural-pcb-ind",
    "B-strict-pcb-defect-s0": "B-pcb-defect",
}


def extract(pkg):
    d = PK / pkg
    yaml = d / "data.yaml"
    if yaml.exists():
        return yaml
    with zipfile.ZipFile(EXP / f"openinspect-trust-v0.1-{pkg}-yolo.zip") as z:
        for n in z.namelist():
            if n.startswith(("images/test/", "labels/test/")):
                z.extract(n, d)
    yaml.write_text(
        f"path: {d.as_posix()}\ntrain: images/test\nval: images/test\ntest: images/test\n"
        "nc: 4\nnames:\n  0: short\n  1: open\n  2: mouse_bite\n  3: spurious_copper\n"
    )
    return yaml


def test_digest(pkg):
    """SHA-256 over sorted (name, bytes-hash) of the test images and labels."""
    h = hashlib.sha256()
    with zipfile.ZipFile(EXP / f"openinspect-trust-v0.1-{pkg}-yolo.zip") as z:
        names = sorted(n for n in z.namelist() if n.startswith(("images/test/", "labels/test/")))
        for n in names:
            h.update(n.encode())
            h.update(hashlib.sha256(z.read(n)).digest())
    return h.hexdigest(), len(names)


res = json.loads(OUT.read_text()) if OUT.exists() else {}
for run, pkg in RUNS.items():
    if run in res:
        continue
    yaml = extract(pkg)
    t = time.time()
    m = YOLO(str(DATA / "models/m7" / f"{run}.pt"))
    r = m.val(data=str(yaml), split="test", imgsz=640, conf=0.001, iou=0.7, max_det=300,
              batch=32, device="cpu", half=False, plots=False, verbose=False,
              project=str(SCR / "valruns"), name=run.replace("/", "_"), exist_ok=True)
    dig, n = test_digest(pkg)
    res[run] = {
        "package": pkg, "test_digest": dig, "test_files": n,
        "mAP50_95": float(r.box.map), "mAP50": float(r.box.map50),
        "precision": float(r.box.mp), "recall": float(r.box.mr),
        "per_class_ap50_95": {int(c): float(v) for c, v in zip(r.box.ap_class_index, r.box.maps[r.box.ap_class_index])},
        "seconds": round(time.time() - t, 1),
    }
    OUT.write_text(json.dumps(res, indent=1))
    print(run, res[run]["mAP50_95"], flush=True)
print("DONE")
