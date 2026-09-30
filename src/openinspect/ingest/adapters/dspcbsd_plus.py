"""Adapter for DsPCBSD+ (figshare 10.6084/m9.figshare.24970329.v1, Lv et al., Sci Data 2024).

Layout observed in ``DsPCBSD+.zip`` on 2026-09-30:

    Hash.py                                    authors' near-duplicate script (never executed)
    Data_COCO/annotations/instances_{train,val}2017.json
    Data_COCO/{train2017,val2017}/*.jpg        10,259 images
    Data_YOLO/images/{train,val}/*.jpg         copies of the same images
    Data_YOLO/labels/{train,val}/*.txt         YOLO boxes, class index = COCO category id - 1

There are no VOC files, no test split and no board identifier. COCO is the canonical format (it names
its classes); YOLO is cross-checked against it.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import PurePosixPath

from openinspect.ingest.adapters.base import (
    AdapterContext,
    AdapterError,
    AdapterResult,
    AdapterSpec,
    Findings,
    image_record,
)
from openinspect.ingest.crosscheck import box_in_bounds, locality_test, match_boxes
from openinspect.ingest.formats import FormatError, load_coco, parse_yolo_label
from openinspect.ingest.imaging import inspect_image
from openinspect.ingest.report import GroupingInfo
from openinspect.provenance.records import AnnotationRecord, ImageRecord, Split

SPLITS: tuple[tuple[Split, str], ...] = (("train", "train2017"), ("val", "val2017"))
PROGRESS_EVERY = 2000
TOLERANCE_PX = 0.5
MIN_FAMILY_FOR_LOCALITY = 50


def name_family(file_name: str) -> str:
    """Shape of a file name: a letter code (S, Y, E), ``data``, ``numN`` (N digits) or ``other``."""
    if match := re.fullmatch(r"([A-Za-z])_\d+\.jpg", file_name):
        return match.group(1)
    if re.fullmatch(r"\d+_data\.jpg", file_name):
        return "data"
    if match := re.fullmatch(r"(\d+)\.jpg", file_name):
        return f"num{len(match.group(1))}"
    if re.fullmatch(r".+ \(\d+\)\.jpg", file_name):
        return "copy_suffix"
    return "other"


def name_number(file_name: str) -> int | None:
    match = re.search(r"\d+", file_name)
    return int(match.group(0)) if match else None


def run(ctx: AdapterContext) -> AdapterResult:
    ctx.require(
        "Data_COCO/annotations/instances_train2017.json",
        "Data_COCO/annotations/instances_val2017.json",
        *(f"Data_COCO/{cname}" for _, cname in SPLITS),
        *(f"Data_YOLO/images/{split}" for split, _ in SPLITS),
        *(f"Data_YOLO/labels/{split}" for split, _ in SPLITS),
    )
    findings = Findings(formats_present=["coco", "yolo"], canonical_format="coco")
    for name in ctx.files_in("."):
        findings.anomaly(
            "non_data_file_in_archive",
            "info",
            "a file that is not data ships in the archive (read as text, never executed)",
            name,
        )
    findings.anomaly(
        "voc_not_shipped",
        "info",
        "the paper and record mention VOC annotations, the archive contains only COCO and YOLO",
    )
    images: list[ImageRecord] = []
    annotations: list[AnnotationRecord] = []
    seen_split: dict[str, str] = {}
    by_family: dict[str, list[tuple[int, int]]] = defaultdict(list)
    family_counts: dict[str, int] = defaultdict(int)
    for split, cname in SPLITS:
        coco = load_coco(ctx.root / f"Data_COCO/annotations/instances_{cname}.json")
        names = [coco.categories[i] for i in sorted(coco.categories)]
        if sorted(coco.categories) != list(range(1, len(names) + 1)):
            raise AdapterError(
                "COCO category ids are not 1..N, the YOLO class mapping cannot be trusted"
            )
        _licence_note(coco.licences, findings)
        dir_files = set(ctx.files_in(f"Data_COCO/{cname}"))
        json_names = {i.file_name for i in coco.images}
        yolo_images = set(ctx.files_in(f"Data_YOLO/images/{split}"))
        yolo_labels = {n.removesuffix(".txt") for n in ctx.files_in(f"Data_YOLO/labels/{split}")}
        findings.orphans(
            "image", present_in="coco_dir", missing_in="coco_json", names=dir_files - json_names
        )
        findings.orphans(
            "image", present_in="coco_json", missing_in="coco_dir", names=json_names - dir_files
        )
        findings.orphans(
            "image", present_in="coco_dir", missing_in="yolo_images", names=dir_files - yolo_images
        )
        findings.orphans(
            "image", present_in="yolo_images", missing_in="coco_dir", names=yolo_images - dir_files
        )
        stems = {PurePosixPath(n).stem for n in dir_files}
        findings.orphans(
            "label", present_in="yolo_labels", missing_in="images", names=yolo_labels - stems
        )
        findings.orphans(
            "image", present_in="coco_dir", missing_in="yolo_labels", names=stems - yolo_labels
        )
        if coco.orphan_annotations:
            findings.anomaly(
                "orphan_annotation_coco_json",
                "warning",
                "annotations that point to an image id the COCO file does not list",
                count=coco.orphan_annotations,
            )
        if coco.unknown_category_annotations:
            findings.anomaly(
                "annotation_unknown_category",
                "warning",
                "annotations with a category id that is not in categories",
                count=coco.unknown_category_annotations,
            )
        for image in sorted(coco.images, key=lambda i: i.file_name):
            if image.file_name not in dir_files:
                continue
            if image.file_name in seen_split:
                findings.anomaly(
                    "name_in_both_splits",
                    "error",
                    "the same file name occurs in train and val",
                    image.file_name,
                )
            seen_split[image.file_name] = split
            rel = f"Data_COCO/{cname}/{image.file_name}"
            info = inspect_image(ctx.root / rel)
            flags: list[str] = []
            if not info.ok:
                findings.anomaly(
                    "image_undecodable", "error", "image cannot be decoded", f"{rel}: {info.error}"
                )
                flags.append("undecodable")
            elif (info.width, info.height) != (image.width, image.height):
                findings.anomaly(
                    "size_mismatch_json_vs_file",
                    "warning",
                    "image size in the COCO file differs from the decoded size",
                    image.file_name,
                )
            if info.exif_orientation not in (None, 1):
                findings.anomaly(
                    "exif_orientation_not_1",
                    "warning",
                    "EXIF orientation is not 1",
                    image.file_name,
                )
            alt = f"Data_YOLO/images/{split}/{image.file_name}"
            alternates: list[str] = []
            if image.file_name in yolo_images:
                if ctx.sha256(alt) == ctx.sha256(rel):
                    alternates.append(alt)
                else:
                    findings.anomaly(
                        "image_copies_differ",
                        "error",
                        "the COCO and YOLO copies of an image differ",
                        image.file_name,
                    )
            boxes = coco.boxes.get(image.id, [])
            stem = PurePosixPath(image.file_name).stem
            if stem in yolo_labels:
                try:
                    yolo = parse_yolo_label(
                        ctx.root / f"Data_YOLO/labels/{split}/{stem}.txt",
                        image.width,
                        image.height,
                        names,
                    )
                except FormatError as exc:
                    findings.anomaly(
                        "yolo_label_unreadable", "error", "a YOLO label file is malformed", str(exc)
                    )
                else:
                    result = match_boxes(boxes, yolo)
                    if result.only_a or result.only_b:
                        findings.anomaly(
                            "coco_yolo_box_count_differs",
                            "error",
                            "COCO and YOLO hold a different number of boxes for an image",
                            image.file_name,
                        )
                    if result.max_deviation > TOLERANCE_PX:
                        findings.anomaly(
                            "coco_yolo_box_deviation",
                            "error",
                            f"COCO and YOLO boxes differ by more than {TOLERANCE_PX} px",
                            image.file_name,
                        )
            if not boxes:
                flags.append("no_annotations")
            width, height = (info.width or image.width), (info.height or image.height)
            for index, box in enumerate(boxes):
                inside = box_in_bounds(box, width, height)
                if not inside:
                    findings.anomaly(
                        "box_out_of_bounds",
                        "warning",
                        "a box is degenerate or leaves the image",
                        image.file_name,
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
            family = name_family(image.file_name)
            family_counts[family] += 1
            number = name_number(image.file_name)
            if info.dhash is not None and number is not None:
                by_family[family].append((number, int(info.dhash, 16)))
            images.append(
                image_record(
                    ctx,
                    rel=rel,
                    info=info,
                    split=split,
                    labels=[b.label for b in boxes],
                    annotation_source="coco",
                    name_family=family,
                    alternates=alternates,
                    flags=flags,
                )
            )
            if len(images) % PROGRESS_EVERY == 0:
                ctx.progress(f"{ctx.slug}: {len(images)} images checked")
    if family_counts.get("copy_suffix"):
        findings.anomaly(
            "windows_copy_suffix_in_name",
            "info",
            "file names of the form 'name (n).jpg' (Windows copy suffix): possible manual copies",
            count=family_counts["copy_suffix"],
        )
    findings.grouping = _grouping(family_counts, by_family)
    findings.notes.append(
        "Hash.py in the archive is the authors' near-duplicate script (16x16 dHash, Hamming distance < 4, "
        "applied per folder); whether and where it was applied to the released images is not documented."
    )
    return AdapterResult(images, annotations, findings)


def _licence_note(licences: list[dict[str, object]], findings: Findings) -> None:
    text = (
        "the COCO files carry a licenses entry with no name and no URL"
        if licences and not any((entry.get("name") or entry.get("url")) for entry in licences)
        else "the COCO files state a licence"
    )
    if text not in findings.archive_says:
        findings.archive_says.append(text)


def _grouping(
    family_counts: dict[str, int], by_family: dict[str, list[tuple[int, int]]]
) -> GroupingInfo:
    evidence = [
        "file-name families: " + ", ".join(f"{k} {v:,}" for k, v in sorted(family_counts.items()))
    ]
    for family, items in sorted(by_family.items()):
        if len(items) < MIN_FAMILY_FOR_LOCALITY:
            continue
        ordered = [h for _, h in sorted(items)]
        test = locality_test(ordered)
        evidence.append(
            f"family {family} ({len(items):,} images): median dHash distance between consecutive numbers "
            f"{test.adjacent_median:g} vs {test.random_median:g} for random pairs; pairs within 8 bits: "
            f"{test.adjacent_close:.0%} vs {test.random_close:.0%}"
        )
    return GroupingInfo(
        key=None,
        quality="none",
        n_groups=None,
        summary=(
            "no board or scene identifier in the archive. File names carry a family code (S, Y, E, digits, "
            "data) and a number, but consecutive numbers are hardly more alike than random pairs, so they "
            "do not identify boards; groups must come from similarity clustering (M3)"
        ),
        evidence=evidence,
    )


SPEC = AdapterSpec(name="dspcbsd_plus", version=1, run=run)
