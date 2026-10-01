"""Small taxonomies, mapped images and an M4 test repository built from synthetic records."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from openinspect.dedup.inventory import ImageItem
from openinspect.provenance.records import AnnotationRecord
from openinspect.taxonomy.config import Taxonomy
from openinspect.taxonomy.mapping import AnnotatedImage, Box, MappedImage, map_image
from tests.factories import accepted_manifest

TAXONOMY: dict[str, Any] = {
    "schema_version": 1,
    "hierarchy": {
        "level_0": "defect",
        "families": {"residue": "extra material", "deficiency": "missing material"},
    },
    "classes": {
        "short": {"family": "residue", "definition": "an unwanted connection of two conductors"},
        "open": {"family": "deficiency", "definition": "a break in a conductor path"},
        "burr": {"family": "residue", "definition": "a small protrusion at an edge"},
        "spur": {"family": "residue", "definition": "a protrusion from a trace edge"},
        "hole": {"family": "deficiency", "definition": "a hole away from its pad centre"},
    },
    "citations": {"src-a": "Paper A, section 2", "src-b": "Paper B, table 1"},
    "mappings": {
        "src-a": {
            "SH": {
                "normalized_label": "short",
                "status": "EXACT",
                "evidence": "'connection between conductors'",
            },
            "OP": {
                "normalized_label": "open",
                "status": "COMPATIBLE",
                "evidence": "'interrupted path', broader",
            },
            "SP": {
                "normalized_label": "spur",
                "status": "EXACT",
                "evidence": "'protrusion along edges'",
            },
            "HB": {
                "normalized_label": "hole",
                "status": "SOURCE_SPECIFIC",
                "evidence": "'hole off its pad centre'",
            },
        },
        "src-b": {
            "short": {
                "normalized_label": "short",
                "status": "EXACT",
                "evidence": "'unintended connection'",
            },
            "open": {
                "normalized_label": "open",
                "status": "EXACT",
                "evidence": "'broken conductive line'",
            },
            "burr": {
                "normalized_label": "burr",
                "status": "AMBIGUOUS",
                "candidate": "spur",
                "evidence": "'tiny burrs at edges', mostly at holes",
            },
            "placeholder": {
                "normalized_label": None,
                "status": "REJECTED",
                "evidence": "a tool's project category",
            },
        },
    },
    "considered_merges": [
        {
            "labels": ["src-b:burr", "src-a:SP"],
            "decision": "not merged",
            "reason": "see the AMBIGUOUS mapping",
        }
    ],
}
DECLARED = {"src-a": ["SH", "OP", "SP", "HB"], "src-b": ["short", "open", "burr"]}


def taxonomy_data(**changes: Any) -> dict[str, Any]:
    data = copy.deepcopy(TAXONOMY)
    data.update(changes)
    return data


def taxonomy(**changes: Any) -> Taxonomy:
    return Taxonomy.model_validate(taxonomy_data(**changes))


def item(
    source: str,
    item_id: str,
    *,
    split: str | None = "train",
    group: str | None = None,
    size: tuple[int, int] = (100, 100),
    flags: tuple[str, ...] = (),
) -> ImageItem:
    return ImageItem(
        source=source,
        item_id=item_id,
        path=Path(item_id),
        sha256="0" * 64,
        split=split,
        group_id=group,
        subgroup_id=None,
        n_annotations=0,
        dhash=None,
        width=size[0],
        height=size[1],
        acquisition_id=f"{source}-camera",
        flags=flags,
    )


def box(
    index: int, label: str, bbox: tuple[float, float, float, float], *, in_bounds: bool = True
) -> Box:
    return Box(index, label, bbox, in_bounds)


def mapped(
    source: str,
    item_id: str,
    boxes: list[Box],
    tax: Taxonomy | None = None,
    **item_args: Any,
) -> MappedImage:
    t = tax or taxonomy()
    return map_image(
        AnnotatedImage(item(source, item_id, **item_args), tuple(boxes)), t, t.benchmark_classes
    )


# --------------------------------------------------------------- an M4 test repository


def write_annotations(
    data: Path, source: str, rows: list[tuple[str, int, str, list[float]]]
) -> None:
    folder = data / "records" / source
    folder.mkdir(parents=True, exist_ok=True)
    lines = [
        AnnotationRecord(
            source_dataset=source,
            source_item_id=item_id,
            ann_index=index,
            original_label=label,
            bbox_xyxy=bbox,
            in_bounds=True,
        ).model_dump_json()
        for item_id, index, label, bbox in rows
    ]
    (folder / "annotations.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_m3(
    root: Path, pairs: list[dict[str, Any]], *, reviewed: int = 0, queued: int = 3
) -> None:
    folder = root / "artifacts" / "m3"
    folder.mkdir(parents=True, exist_ok=True)
    thresholds = {
        "model": "stub",
        "review": 0.9,
        "family": 0.92,
        "near": 0.95,
        "phash_candidate": 4,
        "from_pools": [],
        "from_synthetic": [],
    }
    (folder / "thresholds.json").write_text(json.dumps(thresholds), encoding="utf-8")
    columns = {
        "source_a": [p["source_a"] for p in pairs],
        "image_a": [p["image_a"] for p in pairs],
        "source_b": [p["source_b"] for p in pairs],
        "image_b": [p["image_b"] for p in pairs],
        "category": [p.get("category", "NEAR_DUPLICATE") for p in pairs],
        "cosine": pa.array([p.get("cosine", 0.97) for p in pairs], type=pa.float32()),
        "phash_distance": pa.array([p.get("phash", 2) for p in pairs], type=pa.uint8()),
        "sha256_equal": [p.get("same", False) for p in pairs],
    }
    pq.write_table(pa.table(columns), folder / "duplicate-pairs.parquet")
    lines = ["pair_id,human_decision,human_notes"]
    lines += [f"P{k},{'same' if k < reviewed else ''}," for k in range(queued)]
    (folder / "review-candidates.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def manifest(slug: str, labels: list[str]) -> dict[str, Any]:
    data = accepted_manifest(slug)
    data["content"]["original_classes"] = [{"label": label} for label in labels]
    return data
