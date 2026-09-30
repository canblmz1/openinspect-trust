"""Adapter for PCB-IND v4 (Zenodo 10.5281/zenodo.19723114, Yan et al., Sci Data 2026).

Layout observed in ``PCB-IND_v4.zip`` on 2026-09-30:

    classes.json, README.md
    COCO/annotations/{train,val,test}.json      COCO/images/{train,val,test}/*.jpg
    VOC/Annotations/*.xml                       VOC/ImageSets/Main/{train,val,test}.txt
    VOC/JPEGImages/*.jpg                        (one directory for all splits)
    YOLO/data.yaml                              YOLO/images|labels/{train,val,test}/

Every image exists in three byte-identical copies. The three annotation sets are cross-checked; YOLO
is canonical: it is the only one that holds all 5,932 boxes the paper reports (COCO misses one box,
one VOC file is unreadable). Class ids and names come from ``classes.json``.
"""

from __future__ import annotations

import json
import re
import statistics
from collections import defaultdict
from collections.abc import Mapping
from pathlib import PurePosixPath

import yaml

from openinspect.ingest.adapters.base import (
    AdapterContext,
    AdapterError,
    AdapterResult,
    AdapterSpec,
    Findings,
    image_record,
)
from openinspect.ingest.crosscheck import box_in_bounds, match_boxes
from openinspect.ingest.formats import (
    Box,
    CocoImage,
    FormatError,
    load_coco,
    parse_voc,
    parse_yolo_label,
)
from openinspect.ingest.imaging import inspect_image
from openinspect.ingest.report import GroupingInfo
from openinspect.provenance.records import AnnotationRecord, ImageRecord, Split

SPLITS: tuple[Split, ...] = ("train", "val", "test")
PROGRESS_EVERY = 1000
COCO_TOLERANCE_PX = 0.5
VOC_TOLERANCE_PX = 1.5  # VOC stores integer pixels
NAME = re.compile(r"(\d{4})_([a-z])_(\d+)")
LICENCE_WORDS = re.compile(r"licen[cs]e|CC[ -]BY|creative commons", re.IGNORECASE)


def _readme_licence(readme: str) -> str:
    """What the README says about the licence: its licence section, else the words it uses."""
    lines = readme.splitlines()
    for index, line in enumerate(lines):
        if line.lstrip().startswith("#") and LICENCE_WORDS.search(line):
            body: list[str] = []
            for following in lines[index + 1 :]:
                if following.lstrip().startswith("#"):
                    break
                if following.strip():
                    body.append(following.strip())
                if len(body) == 3:
                    break
            if body:
                title = line.strip("# ").strip()
                return f"README.md section '{title}' says: " + " ".join(body)[:300]
    mentions = sorted({m.group(0) for m in LICENCE_WORDS.finditer(readme)})
    if mentions:
        return "README.md mentions: " + ", ".join(mentions)
    return "README.md does not state a licence"


def _load_classes(ctx: AdapterContext, findings: Findings) -> list[str]:
    data = json.loads((ctx.root / "classes.json").read_text(encoding="utf-8"))
    classes = {int(c["id"]): str(c["name"]) for c in data["classes"]}
    if sorted(classes) != list(range(len(classes))):
        raise AdapterError("classes.json ids are not 0..N-1")
    if data.get("version") != "v4":
        findings.anomaly(
            "classes_json_version",
            "warning",
            f"classes.json says version {data.get('version')!r}, not v4",
        )
    names = [classes[i] for i in range(len(classes))]
    yaml_names = yaml.safe_load((ctx.root / "YOLO/data.yaml").read_text(encoding="utf-8")).get(
        "names"
    )
    if yaml_names != names:
        findings.anomaly(
            "class_map_conflict",
            "error",
            "YOLO/data.yaml names differ from classes.json",
            str(yaml_names),
        )
    return names


def run(ctx: AdapterContext) -> AdapterResult:
    ctx.require(
        "classes.json",
        "README.md",
        "YOLO/data.yaml",
        "VOC/Annotations",
        "VOC/JPEGImages",
        *(f"COCO/annotations/{s}.json" for s in SPLITS),
        *(f"COCO/images/{s}" for s in SPLITS),
        *(f"VOC/ImageSets/Main/{s}.txt" for s in SPLITS),
        *(f"YOLO/images/{s}" for s in SPLITS),
        *(f"YOLO/labels/{s}" for s in SPLITS),
    )
    findings = Findings(formats_present=["coco", "voc", "yolo"], canonical_format="yolo")
    names = _load_classes(ctx, findings)
    readme = (ctx.root / "README.md").read_text(encoding="utf-8", errors="replace")
    findings.archive_says.append(_readme_licence(readme))
    voc_jpg = set(ctx.files_in("VOC/JPEGImages"))
    voc_xml = {n.removesuffix(".xml") for n in ctx.files_in("VOC/Annotations")}
    all_stems: set[str] = set()
    images: list[ImageRecord] = []
    annotations: list[AnnotationRecord] = []
    batch_splits: dict[str, set[str]] = defaultdict(set)
    batch_side_splits: dict[str, set[str]] = defaultdict(set)
    batch_sizes: dict[str, int] = defaultdict(int)
    sides: dict[str, int] = defaultdict(int)
    for split in SPLITS:
        coco = load_coco(ctx.root / f"COCO/annotations/{split}.json")
        if dict(coco.categories) != dict(enumerate(names)):
            findings.anomaly(
                "coco_categories_differ", "error", "COCO categories differ from classes.json", split
            )
        coco_dir = set(ctx.files_in(f"COCO/images/{split}"))
        coco_by_name = {PurePosixPath(i.file_name).name: i for i in coco.images}
        yolo_images = set(ctx.files_in(f"YOLO/images/{split}"))
        yolo_labels = {n.removesuffix(".txt") for n in ctx.files_in(f"YOLO/labels/{split}")}
        voc_list = {
            line.strip()
            for line in (ctx.root / f"VOC/ImageSets/Main/{split}.txt")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        }
        stems = {PurePosixPath(n).stem for n in yolo_images}
        findings.orphans(
            "image",
            present_in="coco_dir",
            missing_in="coco_json",
            names=coco_dir - set(coco_by_name),
        )
        findings.orphans(
            "image",
            present_in="coco_json",
            missing_in="coco_dir",
            names=set(coco_by_name) - coco_dir,
        )
        findings.orphans(
            "image", present_in="yolo_images", missing_in="coco_dir", names=yolo_images - coco_dir
        )
        findings.orphans(
            "image", present_in="coco_dir", missing_in="yolo_images", names=coco_dir - yolo_images
        )
        findings.orphans(
            "image", present_in="yolo_images", missing_in="yolo_labels", names=stems - yolo_labels
        )
        findings.orphans(
            "label", present_in="yolo_labels", missing_in="yolo_images", names=yolo_labels - stems
        )
        findings.orphans(
            "image", present_in="yolo_images", missing_in="voc_imagesets", names=stems - voc_list
        )
        findings.orphans(
            "image", present_in="voc_imagesets", missing_in="yolo_images", names=voc_list - stems
        )
        findings.orphans(
            "image",
            present_in="yolo_images",
            missing_in="voc_jpegimages",
            names=yolo_images - voc_jpg,
        )
        findings.orphans(
            "annotation",
            present_in="yolo_images",
            missing_in="voc_annotations",
            names=stems - voc_xml,
        )
        if coco.orphan_annotations:
            findings.anomaly(
                "orphan_annotation_coco_json",
                "warning",
                "annotations that point to an image id the COCO file does not list",
                count=coco.orphan_annotations,
            )
        for name in sorted(yolo_images):
            stem = PurePosixPath(name).stem
            if stem in all_stems:
                findings.anomaly(
                    "name_in_several_splits", "error", "a file name occurs in several splits", name
                )
            all_stems.add(stem)
            rel = f"YOLO/images/{split}/{name}"
            info = inspect_image(ctx.root / rel)
            flags: list[str] = []
            if not info.ok:
                findings.anomaly(
                    "image_undecodable", "error", "image cannot be decoded", f"{rel}: {info.error}"
                )
                flags.append("undecodable")
            if info.exif_orientation not in (None, 1):
                findings.anomaly(
                    "exif_orientation_not_1", "warning", "EXIF orientation is not 1", name
                )
            alternates = _alternates(ctx, rel, name, split, coco_dir, voc_jpg, findings)
            width, height = info.width or 300, info.height or 300
            boxes: list[Box] = []
            if stem in yolo_labels:
                try:
                    boxes = parse_yolo_label(
                        ctx.root / f"YOLO/labels/{split}/{stem}.txt", width, height, names
                    )
                except FormatError as exc:
                    findings.anomaly(
                        "yolo_label_unreadable", "error", "a YOLO label file is malformed", str(exc)
                    )
                    flags.append("annotation_unreadable")
            _compare_coco(name, boxes, coco_by_name, coco.boxes, flags, findings)
            _compare_voc(ctx, stem, boxes, voc_xml, flags, findings)
            if not boxes:
                flags.append("no_annotations")
            for index, box in enumerate(boxes):
                inside = box_in_bounds(box, width, height)
                if not inside:
                    findings.anomaly(
                        "box_out_of_bounds",
                        "warning",
                        "a box is degenerate or leaves the image",
                        name,
                    )
                annotations.append(
                    AnnotationRecord(
                        source_dataset=ctx.slug,
                        source_item_id=rel,
                        ann_index=index,
                        original_label=box.label,
                        label_id=box.label_id,
                        bbox_xyxy=list(box.xyxy),
                        in_bounds=inside,
                    )
                )
            group = subgroup = None
            if match := NAME.fullmatch(stem):
                group, subgroup = match.group(1), f"{match.group(1)}_{match.group(2)}"
                batch_splits[group].add(split)
                batch_side_splits[subgroup].add(split)
                batch_sizes[group] += 1
                sides[match.group(2)] += 1
            else:
                findings.anomaly(
                    "name_pattern_mismatch", "warning", "file name is not <batch>_<side>_<n>", name
                )
            images.append(
                image_record(
                    ctx,
                    rel=rel,
                    info=info,
                    split=split,
                    labels=[b.label for b in boxes],
                    annotation_source="yolo",
                    group=group,
                    subgroup=subgroup,
                    alternates=alternates,
                    flags=flags,
                )
            )
            if len(images) % PROGRESS_EVERY == 0:
                ctx.progress(f"{ctx.slug}: {len(images)} images checked")
    findings.orphans(
        "image",
        present_in="voc_jpegimages",
        missing_in="yolo_images",
        names=voc_jpg - {f"{s}.jpg" for s in all_stems},
    )
    findings.grouping = _grouping(batch_splits, batch_side_splits, batch_sizes, sides)
    findings.notes.append(
        "README: the release may contain hard negatives, images without annotations that look like defects."
    )
    return AdapterResult(images, annotations, findings)


def _alternates(
    ctx: AdapterContext,
    rel: str,
    name: str,
    split: str,
    coco_dir: set[str],
    voc_jpg: set[str],
    findings: Findings,
) -> list[str]:
    alternates: list[str] = []
    candidates = [
        (f"COCO/images/{split}/{name}", name in coco_dir),
        (f"VOC/JPEGImages/{name}", name in voc_jpg),
    ]
    for alt, exists in candidates:
        if not exists:
            continue
        if ctx.sha256(alt) == ctx.sha256(rel):
            alternates.append(alt)
        else:
            findings.anomaly("image_copies_differ", "error", "the copies of an image differ", name)
    return alternates


def _compare_coco(
    name: str,
    yolo: list[Box],
    coco_by_name: Mapping[str, CocoImage],
    coco_boxes: dict[int, list[Box]],
    flags: list[str],
    findings: Findings,
) -> None:
    image = coco_by_name.get(name)
    if image is None:
        return
    boxes = coco_boxes.get(image.id, [])
    result = match_boxes(boxes, yolo)
    if result.only_b:
        findings.anomaly(
            "coco_missing_box",
            "warning",
            "YOLO holds boxes that the COCO file lacks (YOLO is complete and matches the paper's total)",
            name,
            count=result.only_b,
        )
        flags.append("coco_missing_box")
    if result.only_a:
        findings.anomaly(
            "coco_extra_box", "error", "COCO holds boxes that YOLO lacks", name, count=result.only_a
        )
        flags.append("coco_extra_box")
    if result.max_deviation > COCO_TOLERANCE_PX:
        findings.anomaly("coco_yolo_box_deviation", "error", "COCO and YOLO boxes differ", name)


def _compare_voc(
    ctx: AdapterContext,
    stem: str,
    yolo: list[Box],
    voc_xml: set[str],
    flags: list[str],
    findings: Findings,
) -> None:
    if stem not in voc_xml:
        return
    try:
        voc = parse_voc(ctx.root / f"VOC/Annotations/{stem}.xml")
    except FormatError as exc:
        findings.anomaly(
            "voc_unreadable",
            "warning",
            "a VOC annotation file cannot be parsed (YOLO and COCO still hold its boxes)",
            str(exc),
        )
        flags.append("voc_unreadable")
        return
    result = match_boxes(voc.boxes, yolo)
    if result.only_a or result.only_b or result.max_deviation > VOC_TOLERANCE_PX:
        findings.anomaly("voc_yolo_boxes_differ", "error", "VOC and YOLO boxes differ", stem)


def _grouping(
    batch_splits: dict[str, set[str]],
    batch_side_splits: dict[str, set[str]],
    batch_sizes: dict[str, int],
    sides: dict[str, int],
) -> GroupingInfo:
    sizes = sorted(batch_sizes.values())
    multi = sum(len(v) > 1 for v in batch_splits.values())
    multi_side = sum(len(v) > 1 for v in batch_side_splits.values())
    evidence = [
        f"{len(batch_splits):,} batches, {len(batch_side_splits):,} (batch, side) groups; side letters: "
        + ", ".join(f"{k} {v:,}" for k, v in sorted(sides.items())),
        f"images per batch: min {sizes[0]}, median {statistics.median(sizes):g}, max {sizes[-1]}",
        f"batches that occur in more than one split: {multi:,} of {len(batch_splits):,}",
        f"(batch, side) groups that occur in more than one split: {multi_side:,}",
    ]
    return GroupingInfo(
        key="batch = first 4 characters of the file name; file names are <batch>_<b|t>_<n>",
        quality="explicit",
        n_groups=len(batch_splits),
        summary=(
            "the file name encodes the production batch and the board side; the official split never "
            "separates a (batch, side) group but does split "
            f"{multi:,} batches across two splits, so it is group-aware at (batch, side) level only"
        ),
        evidence=evidence,
    )


SPEC = AdapterSpec(name="pcb_ind", version=1, run=run)
