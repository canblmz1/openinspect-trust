"""Packages for EVREN: YOLO Detection ZIPs built from the committed release manifest (T35).

The package layout is the Ultralytics YOLO detection layout, one of the import formats the EVREN
guide lists: ``data.yaml``, ``images/<split>/<global id>.<ext>`` and
``labels/<split>/<global id>.txt`` with ``class x_center y_center width height`` normalized to the
image. File names are global ids, so split membership can be checked item by item after an
import. ZIPs are deterministic: sorted members, stored (no compression), fixed timestamps and
attributes; the SHA-256 of every member and of the archive is recorded, and the written archive
is read back and compared (invariant I10).
"""

from __future__ import annotations

import csv
import hashlib
import io
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import pyarrow.parquet as pq

from openinspect.files import sha256_bytes
from openinspect.release.config import SPLITS
from openinspect.release.splits import EXCLUDED

ZIP_DATE = (1980, 1, 1, 0, 0, 0)
FORMAT = "YOLO Detection (Ultralytics layout: data.yaml, images/<split>/, labels/<split>/)"


class ExportError(Exception):
    """A package cannot be built or does not match its manifest."""


@dataclass(frozen=True)
class ExportBox:
    class_id: int
    bbox: tuple[float, float, float, float]  # released-image pixels


@dataclass(frozen=True)
class ExportItem:
    global_id: str
    file_name: str
    sha256: str
    source: str
    width: int
    height: int
    labels: tuple[str, ...]  # normalized classes present
    boxes: tuple[ExportBox, ...]
    splits: Mapping[str, str]  # scheme -> split


def read_items(release_dir: Path, items_file: str, annotations_file: str) -> list[ExportItem]:
    """The released items with their boxes and splits, from the committed Parquet files."""
    rows = pq.read_table(release_dir / items_file).to_pylist()
    boxes: dict[str, list[ExportBox]] = {}
    labels: dict[str, set[str]] = {}
    for a in pq.read_table(release_dir / annotations_file).to_pylist():
        boxes.setdefault(a["global_id"], []).append(
            ExportBox(int(a["class_id"]), (a["x_min"], a["y_min"], a["x_max"], a["y_max"]))
        )
        labels.setdefault(a["global_id"], set()).add(str(a["normalized_label"]))
    return [
        ExportItem(
            global_id=r["global_id"],
            file_name=r["file_name"],
            sha256=r["sha256"],
            source=r["source"],
            width=int(r["width"]),
            height=int(r["height"]),
            labels=tuple(sorted(labels.get(r["global_id"], set()))),
            boxes=tuple(boxes.get(r["global_id"], [])),
            splits={k.removeprefix("split_"): v for k, v in r.items() if k.startswith("split_")},
        )
        for r in rows
    ]


def yolo_labels(item: ExportItem) -> str:
    """One line per box: class id and the box centre and size relative to the image."""
    lines = []
    for b in item.boxes:
        x0, y0, x1, y1 = b.bbox
        lines.append(
            f"{b.class_id} {(x0 + x1) / 2 / item.width:.6f} {(y0 + y1) / 2 / item.height:.6f} "
            f"{(x1 - x0) / item.width:.6f} {(y1 - y0) / item.height:.6f}"
        )
    return "".join(f"{line}\n" for line in lines)


def data_yaml(names: Sequence[str], title: str) -> str:
    lines = [
        f"# {title}",
        "path: .",
        "train: images/train",
        "val: images/val",
        "test: images/test",
        f"nc: {len(names)}",
        "names:",
        *(f"  {k}: {name}" for k, name in enumerate(names)),
    ]
    return "\n".join(lines) + "\n"


def package_members(
    items: Sequence[ExportItem],
    scheme: str,
    images_dir: Path,
    names: Sequence[str],
    title: str,
) -> list[tuple[str, bytes]]:
    """(path in the archive, bytes) for every member, sorted; image bytes are checked."""
    members: list[tuple[str, bytes]] = [("data.yaml", data_yaml(names, title).encode("utf-8"))]
    for item in items:
        split = item.splits[scheme]
        if split == EXCLUDED:
            continue
        data = (images_dir / item.file_name).read_bytes()
        if sha256_bytes(data) != item.sha256:
            raise ExportError(f"{item.file_name} differs from the release manifest")
        members.append((f"images/{split}/{item.file_name}", data))
        members.append((f"labels/{split}/{item.global_id}.txt", yolo_labels(item).encode("utf-8")))
    return sorted(members)


def zip_bytes(members: Sequence[tuple[str, bytes]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in members:
            info = zipfile.ZipInfo(name, date_time=ZIP_DATE)
            info.create_system = 3  # the same bytes on every platform
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_STORED
            archive.writestr(info, data)
    return buffer.getvalue()


def verify_zip(path: Path, expected: Mapping[str, str]) -> list[str]:
    """Problems of the archive at ``path`` against member name -> SHA-256 (I10)."""
    problems: list[str] = []
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        for name in sorted(set(expected) - names):
            problems.append(f"missing {name}")
        for name in sorted(names - set(expected)):
            problems.append(f"unexpected {name}")
        for name in sorted(names & set(expected)):
            if hashlib.sha256(archive.read(name)).hexdigest() != expected[name]:
                problems.append(f"{name} differs")
    return problems


def _gain(
    item: ExportItem, classes: set[str], sources: set[str], combos: set[tuple[str, str]]
) -> tuple[int, int, int]:
    return (
        len(set(item.labels) - classes),
        int(item.source not in sources),
        len({(item.source, label) for label in item.labels} - combos),
    )


def select_smoke(
    items: Sequence[ExportItem], scheme: str, counts: Mapping[str, int], seed: int
) -> list[ExportItem]:
    """A few known items per split: new classes first, then new sources, then new pairs of both.

    Ties are broken by a seeded hash of the global id, so the choice is reproducible.
    """
    chosen: list[ExportItem] = []
    for split in SPLITS:
        pool = sorted(
            (i for i in items if i.splits[scheme] == split),
            key=lambda i: hashlib.sha256(f"{seed}:smoke:{i.global_id}".encode()).hexdigest(),
        )
        if len(pool) < counts[split]:
            raise ExportError(
                f"{scheme} {split} has {len(pool)} items, the package needs {counts[split]}"
            )
        rank = {item.global_id: k for k, item in enumerate(pool)}
        classes: set[str] = set()
        sources: set[str] = set()
        combos: set[tuple[str, str]] = set()
        for _ in range(counts[split]):
            best = max(pool, key=lambda i: (_gain(i, classes, sources, combos), -rank[i.global_id]))
            pool.remove(best)
            chosen.append(best)
            classes.update(best.labels)
            sources.add(best.source)
            combos.update((best.source, label) for label in best.labels)
    return chosen


def expected_csv(items: Sequence[ExportItem], scheme: str) -> bytes:
    """The split every item must have after an import, written before the upload."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["global_id", "file_name", "split", "source", "classes", "boxes", "sha256"])
    for item in sorted(items, key=lambda i: (SPLITS.index(i.splits[scheme]), i.global_id)):
        writer.writerow(
            [
                item.global_id,
                item.file_name,
                item.splits[scheme],
                item.source,
                ";".join(item.labels),
                len(item.boxes),
                item.sha256,
            ]
        )
    return buffer.getvalue().encode("utf-8")
