"""Validate a YOLO detection ZIP with the Ultralytics dataset checks (M5.5, P1-4).

Run it with an interpreter that has Ultralytics installed, never the project's environment
(Ultralytics is AGPL-3.0 and stays outside the project; docs/DEPENDENCIES.md):

    <venv-with-ultralytics>/python scripts/validate_export_ultralytics.py PACKAGE.zip OUT.json

The ZIP is extracted to a temporary directory; ``data.yaml`` is parsed by
``ultralytics.data.utils.check_det_dataset`` and every image and label pair goes through
``ultralytics.data.utils.verify_image_label``, the function the Ultralytics loader runs before
training. Nothing of OpenInspect is imported.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path

import ultralytics
from ultralytics.data.utils import check_det_dataset, verify_image_label

SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}


def main(package: Path, out: Path) -> int:
    data = package.read_bytes()
    result: dict[str, object] = {
        "tool": "ultralytics",
        "version": ultralytics.__version__,
        "functions": [
            "ultralytics.data.utils.check_det_dataset",
            "ultralytics.data.utils.verify_image_label",
        ],
        "package": package.name,
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        zipfile.ZipFile(package).extractall(root)
        previous = Path.cwd()
        os.chdir(root)  # data.yaml says `path: .`
        try:
            dataset = check_det_dataset(str(root / "data.yaml"), autodownload=False)
        finally:
            os.chdir(previous)
        names = dataset["names"]
        nc = int(dataset["nc"])
        result["names"] = [names[k] for k in sorted(names)]
        result["nc"] = nc
        totals: Counter[str] = Counter()
        per_split: dict[str, Counter[str]] = {}
        per_class: Counter[int] = Counter()
        messages: list[str] = []
        for split_dir in sorted((root / "images").iterdir()):
            split = split_dir.name
            counts: Counter[str] = Counter()
            for image in sorted(p for p in split_dir.iterdir() if p.suffix.lower() in SUFFIXES):
                label = root / "labels" / split / f"{image.stem}.txt"
                out_args = (str(image), str(label), "", False, nc, 0, 0, False)
                _, lb, _shape, _, _, nm, nf, ne, nc_bad, msg = verify_image_label(out_args)
                counts["images"] += 1
                counts["missing_labels"] += nm
                counts["found_labels"] += nf
                counts["empty_labels"] += ne
                counts["corrupt"] += nc_bad
                if lb is not None and len(lb):
                    counts["boxes"] += len(lb)
                    per_class.update(int(c) for c in lb[:, 0])
                if msg:
                    messages.append(msg.strip())
            per_split[split] = counts
            totals.update(counts)
        result["splits"] = {k: dict(v) for k, v in per_split.items()}
        result["totals"] = dict(totals)
        result["boxes_per_class"] = {result["names"][k]: per_class[k] for k in range(nc)}  # type: ignore[index]
        result["messages"] = messages[:50]
        result["messages_total"] = len(messages)
        result["ok"] = totals["corrupt"] == 0 and totals["missing_labels"] == 0 and not messages
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("package", "version", "totals", "ok")}))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]), Path(sys.argv[2])))
