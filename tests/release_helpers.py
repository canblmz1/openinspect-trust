"""Candidates, boxes and a small synthetic repository with data for the release tests."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import yaml
from PIL import Image

from openinspect.release.ids import global_id
from openinspect.release.pool import Candidate, ReleaseBox
from openinspect.taxonomy.mapping import Box, MappedBox
from tests.dedup_helpers import Spec, make_image, write_items, write_records
from tests.taxonomy_helpers import item, manifest, write_annotations

CLASSES = ("short", "open")


def mbox(
    index: int,
    label: str,
    bbox: tuple[float, float, float, float],
    *,
    benchmark: bool = True,
    normalized: str | None = None,
) -> MappedBox:
    return MappedBox(
        box=Box(index, label, bbox, True),
        normalized_label=normalized or label,
        status="EXACT" if benchmark else "SOURCE_SPECIFIC",
        benchmark=benchmark,
    )


def candidate(
    source: str,
    item_id: str,
    labels: tuple[str, ...] = ("short",),
    *,
    group: str | None = None,
    crop: tuple[int, int, int, int] | None = None,
    split: str | None = "train",
    sha: str | None = None,
) -> Candidate:
    content = sha or hashlib.sha256(f"{source}:{item_id}".encode()).hexdigest()
    image = dataclasses.replace(item(source, item_id, split=split, group=group), sha256=content)
    gid = global_id(source, content, crop)
    boxes = tuple(
        ReleaseBox(k, label, label, "EXACT", CLASSES.index(label), (1, 1, 5, 5), (1, 1, 5, 5))
        for k, label in enumerate(labels)
    )
    return Candidate(gid, image, crop, 100, 100, boxes)


# ------------------------------------------------------------------- a release test repository

TAXONOMY: dict[str, Any] = {
    "schema_version": 1,
    "hierarchy": {"level_0": "defect", "families": {"f": "a family of defects"}},
    "classes": {
        "short": {"family": "f", "definition": "an unwanted connection of two conductors"},
        "open": {"family": "f", "definition": "a break in a conductor path"},
        "spur": {"family": "f", "definition": "a protrusion from a trace edge"},
    },
    "citations": {"src-a": "Paper A", "src-b": "Paper B", "src-c": "Paper C"},
    "mappings": {
        "src-a": {
            "SH": {"normalized_label": "short", "status": "EXACT", "evidence": "'a connection'"},
            "OP": {"normalized_label": "open", "status": "EXACT", "evidence": "'a broken path'"},
            "SP": {"normalized_label": "spur", "status": "EXACT", "evidence": "'a protrusion'"},
        },
        "src-b": {
            "short": {"normalized_label": "short", "status": "EXACT", "evidence": "'a connection'"},
            "open": {
                "normalized_label": "open",
                "status": "COMPATIBLE",
                "evidence": "'a break', wider",
            },
        },
        "src-c": {
            "short": {"normalized_label": "short", "status": "EXACT", "evidence": "'a connection'"},
            "open": {"normalized_label": "open", "status": "EXACT", "evidence": "'a broken path'"},
            "spur": {"normalized_label": "spur", "status": "EXACT", "evidence": "'a protrusion'"},
        },
    },
}
RELEASE: dict[str, Any] = {
    "schema_version": 1,
    "version": "v0.1",
    "seed": 0,
    "size": {"min": 5, "max": 100},
    "max_source_share": 0.5,
    "negatives": "exclude",
    "crops": {"src-c": {"min_side_px": 100, "margin": 0.1, "format": "png"}},
    "splits": {
        "ratios": {"train": 0.6, "val": 0.2, "test": 0.2},
        "held_out_val": 0.25,
        "canonical": "A1",
    },
    "smoke": {"scheme": "A1", "counts": {"train": 2, "val": 1, "test": 1}},
}
DEDUP = """schema_version: 1
preprocessing:
  version: v1
backend: cpu-fp32
default_model: stub
models:
  stub:
    model_id: stub/model
    revision: "0000000000000000000000000000000000000000"
    weights_file: model.safetensors
    weights_sha256: "0000000000000000000000000000000000000000000000000000000000000000"
    dim: 24
    licence: Apache-2.0
sources:
  src-a: {acquisition_id: camera-a}
  src-b: {acquisition_id: camera-a, group_id: batch}
  src-c: {acquisition_id: scanner, group_id: family}
"""
DECLARED = {
    "src-a": ["SH", "OP", "SP"],
    "src-b": ["short", "open"],
    "src-c": ["short", "open", "spur"],
}


def _big(seed: int) -> Image.Image:
    return make_image(seed, size=(64, 48)).resize((400, 400))


def build_world(root: Path, data: Path) -> None:
    """Configs, manifests, records, images and M3 artifacts for three sources."""
    for slug, labels in DECLARED.items():
        path = root / "manifests" / "sources" / f"{slug}.yaml"
        path.write_text(yaml.safe_dump(manifest(slug, labels), sort_keys=False), encoding="utf-8")
    configs = root / "configs"
    (configs / "taxonomy.yaml").write_text(
        yaml.safe_dump(TAXONOMY, sort_keys=False), encoding="utf-8"
    )
    (configs / "release.yaml").write_text(
        yaml.safe_dump(RELEASE, sort_keys=False), encoding="utf-8"
    )
    (configs / "dedup.yaml").write_text(DEDUP, encoding="utf-8")
    a = [Spec(f"a{k:02d}.png", make_image(k), "train" if k % 5 else "val") for k in range(12)]
    b = [
        Spec(f"b{k:02d}.png", make_image(100 + k), "test" if k > 8 else "train", f"B{k // 3}")
        for k in range(12)
    ]
    c = [Spec(f"c{k}.png", _big(200 + k), None, f"F{k % 2}") for k in range(3)]
    for slug, specs in (("src-a", a), ("src-b", b), ("src-c", c)):
        write_records(data, slug, write_items(data, slug, specs))
    write_annotations(
        data,
        "src-a",
        [(f"a{k:02d}.png", 0, ("SH", "OP")[k % 2], [5.0, 5.0, 20.0, 20.0]) for k in range(11)]
        + [("a11.png", 0, "SP", [5.0, 5.0, 20.0, 20.0])],
    )
    write_annotations(
        data,
        "src-b",
        [(f"b{k:02d}.png", 0, ("short", "open")[k % 2], [8.0, 8.0, 30.0, 30.0]) for k in range(11)],
    )
    write_annotations(
        data,
        "src-c",
        [
            ("c0.png", 0, "short", [20.0, 20.0, 60.0, 60.0]),
            ("c0.png", 1, "open", [250.0, 250.0, 300.0, 300.0]),
            ("c0.png", 2, "spur", [300.0, 40.0, 330.0, 70.0]),
            ("c1.png", 0, "short", [150.0, 150.0, 190.0, 190.0]),
            ("c1.png", 1, "open", [170.0, 170.0, 200.0, 210.0]),
            ("c2.png", 0, "open", [10.0, 300.0, 50.0, 340.0]),
            ("c2.png", 1, "short", [200.0, 20.0, 240.0, 60.0]),
        ],
    )
    m3 = root / "artifacts" / "m3"
    m3.mkdir(parents=True, exist_ok=True)
    (m3 / "audit.json").write_text(
        json.dumps({"levels": [{"level": "family", "chained_sources": ["src-c"]}]}),
        encoding="utf-8",
    )
    (m3 / "thresholds.json").write_text("{}", encoding="utf-8")
    pq.write_table(
        pa.table(
            {
                "group_id": ["VSG-family-1", "VSG-family-2", "VSG-near-1"],
                "level": ["family", "family", "near"],
                "members": [
                    ["src-a:a00.png", "src-a:a01.png", "src-b:b00.png"],
                    ["src-a:a02.png", "src-a:a03.png"],
                    ["src-c:c0.png", "src-c:c2.png"],
                ],
            }
        ),
        m3 / "leakage-groups.parquet",
    )
    pq.write_table(
        pa.table(
            {
                "source_a": ["src-a", "src-a", "src-a"],
                "image_a": ["a00.png", "a02.png", "a04.png"],
                "source_b": ["src-b", "src-a", "src-a"],
                "image_b": ["b00.png", "a03.png", "a06.png"],
                "category": ["SAME_FAMILY_OR_SCENE", "NEAR_DUPLICATE", "REVIEW_REQUIRED"],
                "cosine": pa.array([0.93, 0.97, 0.5], type=pa.float32()),
                "phash_distance": pa.array([9, 2, 3], type=pa.uint8()),
                "sha256_equal": [False, False, False],
            }
        ),
        m3 / "duplicate-pairs.parquet",
    )
    (m3 / "review-candidates.csv").write_text(
        "pair_id,human_decision\nP1,\nP2,\n", encoding="utf-8"
    )
