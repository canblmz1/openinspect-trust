"""Tiny synthetic archives that mimic the real layouts of the three sources (no real data)."""

from __future__ import annotations

import json
import random
import zipfile
from pathlib import Path
from typing import Any

from PIL import Image

Box = tuple[int, int, int, int]  # x0, y0, x1, y1 in pixels


def write_jpeg(path: Path, seed: int, size: tuple[int, int] = (32, 32)) -> None:
    """A deterministic noise image: every seed gives different bytes."""
    rng = random.Random(seed)
    image = Image.new("RGB", size)
    image.putdata(
        [
            (rng.randrange(256), rng.randrange(256), rng.randrange(256))
            for _ in range(size[0] * size[1])
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "JPEG", quality=95)


def yolo_line(class_id: int, box: Box, size: tuple[int, int]) -> str:
    w, h = size
    x0, y0, x1, y1 = box
    return f"{class_id} {(x0 + x1) / 2 / w:.6f} {(y0 + y1) / 2 / h:.6f} {(x1 - x0) / w:.6f} {(y1 - y0) / h:.6f}"


def zip_tree(root: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            zf.write(path, path.relative_to(root).as_posix())


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


# ----------------------------------------------------------------------------- DsPCBSD+

DSP_CLASSES = ["SH", "SP", "SC"]
DSP_PLAN: dict[str, list[tuple[str, list[tuple[int, Box]]]]] = {
    "train": [
        ("S_00000001.jpg", [(1, (2, 3, 12, 13)), (2, (5, 5, 20, 25))]),
        ("Y_000001.jpg", [(3, (1, 1, 30, 30))]),
        ("0000001.jpg", []),
        ("AAA (1).jpg", [(1, (4, 4, 10, 10))]),
    ],
    "val": [
        ("E_000002.jpg", [(1, (6, 6, 16, 16))]),
        ("S_00000009.jpg", [(2, (3, 3, 9, 9)), (3, (10, 10, 20, 20))]),
    ],
}
DSP_IMAGES, DSP_BOXES = 6, 7


def build_dspcbsd_plus(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "Hash.py").write_text("print('the authors script, never executed')\n", encoding="utf-8")
    seed = 0
    for split, cname in (("train", "train2017"), ("val", "val2017")):
        images: list[dict[str, Any]] = []
        annotations: list[dict[str, Any]] = []
        for image_id, (name, boxes) in enumerate(DSP_PLAN[split]):
            seed += 1
            write_jpeg(root / f"Data_COCO/{cname}/{name}", seed)
            (root / f"Data_YOLO/images/{split}").mkdir(parents=True, exist_ok=True)
            (root / f"Data_YOLO/images/{split}/{name}").write_bytes(
                (root / f"Data_COCO/{cname}/{name}").read_bytes()
            )
            images.append({"id": image_id, "file_name": name, "width": 32, "height": 32})
            lines = []
            for class_id, box in boxes:
                x0, y0, x1, y1 = box
                annotations.append(
                    {
                        "id": len(annotations),
                        "image_id": image_id,
                        "category_id": class_id,
                        "bbox": [x0, y0, x1 - x0, y1 - y0],
                        "iscrowd": 0,
                    }
                )
                lines.append(yolo_line(class_id - 1, box, (32, 32)))
            label = root / f"Data_YOLO/labels/{split}/{Path(name).stem}.txt"
            label.parent.mkdir(parents=True, exist_ok=True)
            label.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        _write_json(
            root / f"Data_COCO/annotations/instances_{cname}.json",
            {
                "info": {},
                "licenses": [{"id": 1, "name": None, "url": None}],
                "categories": [{"id": i + 1, "name": n} for i, n in enumerate(DSP_CLASSES)],
                "images": images,
                "annotations": annotations,
            },
        )


# ------------------------------------------------------------------------------ PCB-IND

IND_CLASSES = ["mouse_bite", "missing_copper", "scratch"]
IND_PLAN: dict[str, list[tuple[str, list[tuple[int, Box]]]]] = {
    "train": [
        ("5771_b_001", [(0, (10, 10, 20, 22))]),
        ("5771_t_002", [(1, (5, 6, 15, 16)), (2, (20, 20, 30, 30))]),
        ("5772_b_003", []),
    ],
    "val": [("5773_b_001", [(2, (8, 8, 18, 18))])],
    "test": [("5774_t_001", [(0, (2, 2, 12, 12))])],
}
IND_IMAGES, IND_BOXES = 5, 5
IND_SIZE = (32, 32)


def build_pcb_ind(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _write_json(
        root / "classes.json",
        {
            "dataset_name": "PCB-IND",
            "version": "v4",
            "num_classes": len(IND_CLASSES),
            "classes": [{"id": i, "name": n} for i, n in enumerate(IND_CLASSES)],
        },
    )
    (root / "README.md").write_text(
        "# Synthetic PCB-IND\n\nNothing about rights is written here.\n", encoding="utf-8"
    )
    (root / "YOLO").mkdir(parents=True, exist_ok=True)
    (root / "YOLO/data.yaml").write_text(
        "path: .\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n"
        + "".join(f"- {n}\n" for n in IND_CLASSES),
        encoding="utf-8",
    )
    seed = 100
    for split, items in IND_PLAN.items():
        images: list[dict[str, Any]] = []
        annotations: list[dict[str, Any]] = []
        (root / "VOC/ImageSets/Main").mkdir(parents=True, exist_ok=True)
        (root / f"VOC/ImageSets/Main/{split}.txt").write_text(
            "".join(f"{s}\n" for s, _ in items), encoding="utf-8"
        )
        (root / "VOC/Annotations").mkdir(parents=True, exist_ok=True)
        for image_id, (stem, boxes) in enumerate(items):
            seed += 1
            name = f"{stem}.jpg"
            write_jpeg(root / f"YOLO/images/{split}/{name}", seed, IND_SIZE)
            data = (root / f"YOLO/images/{split}/{name}").read_bytes()
            for copy in (f"COCO/images/{split}/{name}", f"VOC/JPEGImages/{name}"):
                (root / copy).parent.mkdir(parents=True, exist_ok=True)
                (root / copy).write_bytes(data)
            images.append(
                {"id": image_id, "file_name": f"images/{split}/{name}", "width": 32, "height": 32}
            )
            lines, objects = [], []
            for class_id, box in boxes:
                x0, y0, x1, y1 = box
                annotations.append(
                    {
                        "id": len(annotations),
                        "image_id": image_id,
                        "category_id": class_id,
                        "bbox": [x0, y0, x1 - x0, y1 - y0],
                        "iscrowd": 0,
                    }
                )
                lines.append(yolo_line(class_id, box, IND_SIZE))
                objects.append(
                    f"<object><name>{IND_CLASSES[class_id]}</name><bndbox><xmin>{x0}</xmin><ymin>{y0}</ymin>"
                    f"<xmax>{x1}</xmax><ymax>{y1}</ymax></bndbox></object>"
                )
            label = root / f"YOLO/labels/{split}/{stem}.txt"
            label.parent.mkdir(parents=True, exist_ok=True)
            label.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
            (root / f"VOC/Annotations/{stem}.xml").write_text(
                f"<annotation><filename>{name}</filename><size><width>32</width><height>32</height>"
                f"<depth>3</depth></size>{''.join(objects)}</annotation>",
                encoding="utf-8",
            )
        _write_json(
            root / f"COCO/annotations/{split}.json",
            {
                "images": images,
                "annotations": annotations,
                "categories": [{"id": i, "name": n} for i, n in enumerate(IND_CLASSES)],
            },
        )


# --------------------------------------------------------------------------- PCB-Defect

DEF_CLASSES = ["short", "spur"]
DEF_PLAN: list[tuple[str, str, list[tuple[int, Box]]]] = [
    ("pcb_defect_001.jpg", "61-1-1.png", [(1, (5, 5, 25, 20))]),
    ("pcb_defect_002.jpg", "61-1-2.png", [(2, (10, 10, 30, 30)), (1, (2, 2, 9, 9))]),
    ("pcb_defect_003.jpg", "62-1-1.png", [(2, (4, 4, 14, 14))]),
    ("pcb_defect_004.jpg", "62-2-1.png", [(1, (20, 10, 40, 30))]),
]
DEF_IMAGES, DEF_BOXES = 4, 5


def build_pcb_defect(root: Path) -> None:
    images: list[dict[str, Any]] = []
    annotations: list[dict[str, Any]] = []
    for image_id, (name, original, boxes) in enumerate(DEF_PLAN):
        write_jpeg(root / f"PCB_Defect/images/{name}", 200 + image_id, (64, 48))
        images.append(
            {
                "id": image_id,
                "license": 1,
                "file_name": name,
                "width": 64,
                "height": 48,
                "extra": {"name": original},
            }
        )
        for class_id, box in boxes:
            x0, y0, x1, y1 = box
            annotations.append(
                {
                    "id": len(annotations),
                    "image_id": image_id,
                    "category_id": class_id,
                    "bbox": [x0, y0, x1 - x0, y1 - y0],
                    "iscrowd": 0,
                }
            )
    _write_json(
        root / "PCB_Defect/annotation/_annotations.coco.json",
        {
            "licenses": [
                {
                    "id": 1,
                    "url": "https://creativecommons.org/licenses/by/4.0/",
                    "name": "CC BY 4.0",
                }
            ],
            "categories": [{"id": 0, "name": "detecting-pcb-defects", "supercategory": "none"}]
            + [
                {"id": i + 1, "name": n, "supercategory": "detecting-pcb-defects"}
                for i, n in enumerate(DEF_CLASSES)
            ],
            "images": images,
            "annotations": annotations,
        },
    )
