"""Synthetic release items for the M5.5 tests: no data directory, no real release."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from PIL import Image

from openinspect.dedup.inventory import ImageItem
from openinspect.release.pool import Candidate, ReleaseBox

CLASSES = ("short", "open", "mouse_bite", "spurious_copper")


def box(label: str, k: int = 0, size: float = 20.0, ann: int = 0) -> ReleaseBox:
    x = 10.0 + 5 * k
    return ReleaseBox(
        source_ann_index=ann,
        original_label=label,
        normalized_label=label,
        mapping_status="EXACT",
        class_id=CLASSES.index(label),
        bbox=(x, x, x + size, x + size),
        bbox_source=(x, x, x + size, x + size),
    )


def candidate(
    gid: str,
    source: str,
    labels: tuple[str, ...] = ("short",),
    *,
    item_id: str | None = None,
    group_id: str | None = None,
    crop: tuple[int, int, int, int] | None = None,
    size: int = 100,
) -> Candidate:
    image = ImageItem(
        source=source,
        item_id=item_id or f"{gid}.jpg",
        path=Path(f"{gid}.jpg"),
        sha256="0" * 64,
        split=None,
        group_id=group_id,
        subgroup_id=None,
        n_annotations=len(labels),
        dhash=None,
        width=size,
        height=size,
    )
    return Candidate(
        global_id=gid,
        item=image,
        crop=crop,
        width=size,
        height=size,
        boxes=tuple(box(label, k, ann=k) for k, label in enumerate(labels)),
    )


def pool(groups_per_source: int = 12) -> tuple[list[Candidate], list[str]]:
    """Three sources: pairs and triples of grouped items, singletons, and one large group."""
    items: list[Candidate] = []
    keys: list[str] = []
    for source in ("src-a", "src-b", "src-c"):
        labels_cycle = [
            ("short",),
            ("open",),
            ("mouse_bite",),
            ("spurious_copper",),
            ("short", "open"),
        ]
        for g in range(groups_per_source):
            size = 2 + g % 2
            for m in range(size):
                gid = f"OI_{source}_g{g:02d}m{m}"
                items.append(candidate(gid, source, labels_cycle[(g + m) % len(labels_cycle)]))
                keys.append(f"{source}:group{g}")
        for s in range(30):
            gid = f"OI_{source}_s{s:02d}"
            items.append(candidate(gid, source, labels_cycle[s % len(labels_cycle)]))
            keys.append(gid)
        for m in range(60):
            gid = f"OI_{source}_big{m:02d}"
            items.append(candidate(gid, source, labels_cycle[m % len(labels_cycle)]))
            keys.append(f"{source}:big")
    return items, keys


def png(width: int = 40, height: int = 30, colour: tuple[int, int, int] = (120, 80, 40)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buffer, format="PNG")
    return buffer.getvalue()


def yolo_zip(
    labels: dict[str, str],
    *,
    images: dict[str, bytes] | None = None,
    data_yaml: str | None = None,
) -> bytes:
    """A YOLO package; ``labels`` maps ``split/stem`` to the label file text."""
    names = data_yaml or (
        "path: .\ntrain: images/train\nval: images/val\ntest: images/test\nnc: 4\nnames:\n"
        + "".join(f"  {k}: {n}\n" for k, n in enumerate(CLASSES))
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("data.yaml", names)
        for key, text in labels.items():
            split, stem = key.split("/")
            archive.writestr(f"labels/{split}/{stem}.txt", text)
        for key, blob in (images if images is not None else {k: png() for k in labels}).items():
            split, stem = key.split("/")
            archive.writestr(f"images/{split}/{stem}.png", blob)
    return buffer.getvalue()
