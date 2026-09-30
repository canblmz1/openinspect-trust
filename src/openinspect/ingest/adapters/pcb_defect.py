"""Adapter for PCB-Defect (Mendeley Data 10.17632/vdj74sngvn.1, Rashid et al., Data in Brief).

Layout observed in ``PCB_Defect.zip`` on 2026-09-30:

    PCB_Defect/annotation/_annotations.coco.json    (Roboflow export, COCO)
    PCB_Defect/images/pcb_defect_NNN.jpg            230 images

There is no train/val/test split. The COCO ``images[].extra.name`` keeps the original scan name
(``<A>-<B>-<C>.png``); ``A`` (22 values) behaves like a board design family, see the grouping evidence.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter

from openinspect.ingest.adapters.base import (
    AdapterContext,
    AdapterResult,
    AdapterSpec,
    Findings,
    image_record,
)
from openinspect.ingest.crosscheck import box_in_bounds, nearest_neighbour_test
from openinspect.ingest.formats import load_coco
from openinspect.ingest.imaging import inspect_image
from openinspect.ingest.report import GroupingInfo
from openinspect.provenance.records import AnnotationRecord, ImageRecord

ORIGINAL_NAME = re.compile(r"(\d+)-(\d+)-(\d+)\.png")
PROGRESS_EVERY = 50
THUMBNAIL = 32


def run(ctx: AdapterContext) -> AdapterResult:
    ctx.require("PCB_Defect/annotation/_annotations.coco.json", "PCB_Defect/images")
    findings = Findings(formats_present=["coco"], canonical_format="coco")
    coco = load_coco(ctx.root / "PCB_Defect/annotation/_annotations.coco.json")
    on_disk = set(ctx.files_in("PCB_Defect/images"))
    listed = {i.file_name for i in coco.images}
    findings.orphans(
        "image", present_in="images_dir", missing_in="coco_json", names=on_disk - listed
    )
    findings.orphans(
        "image", present_in="coco_json", missing_in="images_dir", names=listed - on_disk
    )
    if coco.orphan_annotations:
        findings.anomaly(
            "orphan_annotation_coco_json",
            "warning",
            "annotations that point to an image id the COCO file does not list",
            count=coco.orphan_annotations,
        )
    unused = [
        n for i, n in sorted(coco.categories.items()) if not coco.category_annotation_counts.get(i)
    ]
    for name in unused:
        findings.anomaly(
            "unused_category",
            "info",
            "a COCO category without any annotation (Roboflow's project placeholder); not a class",
            name,
        )
    for licence in coco.licences:
        findings.archive_says.append(
            f"COCO file states licence '{licence.get('name')}' ({licence.get('url')})"
        )
    images: list[ImageRecord] = []
    annotations: list[AnnotationRecord] = []
    thumbnails: list[bytes] = []
    design: list[str] = []
    design_variant: list[str] = []
    for image in sorted(coco.images, key=lambda i: i.file_name):
        if image.file_name not in on_disk:
            continue
        rel = f"PCB_Defect/images/{image.file_name}"
        info = inspect_image(ctx.root / rel, thumbnail=THUMBNAIL)
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
                "exif_orientation_not_1", "warning", "EXIF orientation is not 1", image.file_name
            )
        group = subgroup = None
        if image.extra_name and (match := ORIGINAL_NAME.fullmatch(image.extra_name)):
            group, subgroup = match.group(1), f"{match.group(1)}-{match.group(2)}"
            if info.thumbnail is not None:
                thumbnails.append(info.thumbnail)
                design.append(group)
                design_variant.append(subgroup)
        else:
            findings.anomaly(
                "original_name_unparsed",
                "warning",
                "extra.name is missing or not <A>-<B>-<C>.png",
                image.file_name,
            )
        boxes = coco.boxes.get(image.id, [])
        if not boxes:
            flags.append("no_annotations")
        width, height = info.width or image.width, info.height or image.height
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
        images.append(
            image_record(
                ctx,
                rel=rel,
                info=info,
                split=None,
                labels=[b.label for b in boxes],
                annotation_source="coco",
                group=group,
                subgroup=subgroup,
                original_name=image.extra_name,
                flags=flags,
            )
        )
        if len(images) % PROGRESS_EVERY == 0:
            ctx.progress(f"{ctx.slug}: {len(images)} images checked")
    findings.grouping = _grouping(thumbnails, design, design_variant)
    findings.notes.append(
        "The paper reports one image per physical board; the original names show only 22 design families "
        "across 230 images, so images of one family share their board layout."
    )
    return AdapterResult(images, annotations, findings)


def _grouping(
    thumbnails: list[bytes], design: list[str], design_variant: list[str]
) -> GroupingInfo:
    if len(thumbnails) < 2:
        return GroupingInfo(
            key=None, quality="none", summary="no usable original names", evidence=[]
        )
    by_design = nearest_neighbour_test(thumbnails, design)
    by_variant = nearest_neighbour_test(thumbnails, design_variant)
    sizes = sorted(Counter(design).values())
    evidence = [
        f"{len(set(design))} values of A and {len(set(design_variant))} values of (A, B) over "
        f"{len(design)} images; images per A: min {sizes[0]}, median {statistics.median(sizes):g}, max {sizes[-1]}",
        f"nearest neighbour by {THUMBNAIL}x{THUMBNAIL} grayscale correlation shares A for "
        f"{by_design.hits}/{by_design.n} images ({by_design.rate:.0%}; chance {by_design.chance:.0%}) "
        f"and shares (A, B) for {by_variant.hits}/{by_variant.n} ({by_variant.rate:.0%}; chance "
        f"{by_variant.chance:.0%})",
    ]
    return GroupingInfo(
        key="A of the original scan name <A>-<B>-<C>.png (extra.name in the COCO file); (A, B) is finer",
        quality="derived",
        n_groups=len(set(design)),
        summary=(
            "the COCO file keeps the original scan name of each image; its first field behaves like a "
            "board design family (appearance predicts it far better than chance), but no document "
            "defines the fields"
        ),
        evidence=evidence,
    )


SPEC = AdapterSpec(name="pcb_defect", version=1, run=run)
