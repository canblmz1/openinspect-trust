"""The M3 artifacts: Parquet tables, the review queue as CSV and the audit as JSON (M3J).

String columns are dictionary-encoded (one entry per image, an index per row), so the tables stay
small in memory and on disk however many pairs there are. Every file is written to a temporary
name and renamed, and rows are in a fixed order, so the same inputs give the same bytes.
"""

from __future__ import annotations

import csv
import hashlib
import io
import os
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from numpy.typing import NDArray

from openinspect.dedup.analysis import DECISION, AnalysisResult, PairTable, ReviewRow
from openinspect.dedup.audit_models import Audit
from openinspect.dedup.compute import FeatureSet
from openinspect.dedup.leakage import GroupRow
from openinspect.dedup.thresholds import CATEGORIES

PAIRS = "duplicate-pairs.parquet"
NEIGHBOURS = "nearest-neighbors.parquet"
GROUPS = "leakage-groups.parquet"
REVIEW = "review-candidates.csv"
AUDIT = "audit.json"
REVIEW_COLUMNS = (
    "pair_id",
    "stratum",
    "suggested_category",
    "cosine",
    "phash_distance",
    "dhash_distance",
    "source_a",
    "image_a",
    "split_a",
    "group_a",
    "subgroup_a",
    "source_b",
    "image_b",
    "split_b",
    "group_b",
    "subgroup_b",
    "group_near",
    "group_family",
    "reviewer_decision",
    "reviewer_note",
)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _replace(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def _encoded(values: Sequence[str | None], index: NDArray[np.int64]) -> pa.DictionaryArray:
    """``values[index[r]]`` for every row r, as a dictionary array (``None`` stays null)."""
    dictionary = sorted({v for v in values if v is not None})
    position = {value: code for code, value in enumerate(dictionary)}
    per_value = np.array([position[v] if v is not None else -1 for v in values], dtype=np.int32)
    codes = per_value[index] if len(values) else np.empty(0, dtype=np.int32)
    return pa.DictionaryArray.from_arrays(
        pa.array(codes, type=pa.int32(), mask=codes < 0), pa.array(dictionary, type=pa.string())
    )


def _same_group(
    ids: Sequence[str | None], i: NDArray[np.int64], j: NDArray[np.int64]
) -> pa.DictionaryArray:
    """The group id shared by both images of each pair, or null."""
    dictionary = sorted({v for v in ids if v is not None})
    position = {value: code for code, value in enumerate(dictionary)}
    per_image = np.array([position[v] if v is not None else -1 for v in ids], dtype=np.int32)
    a, b = per_image[i], per_image[j]
    codes = np.where((a >= 0) & (a == b), a, -1).astype(np.int32)
    return pa.DictionaryArray.from_arrays(
        pa.array(codes, type=pa.int32(), mask=codes < 0), pa.array(dictionary, type=pa.string())
    )


def _codes(values: Sequence[str]) -> NDArray[np.int32]:
    names = sorted(set(values))
    return np.array([names.index(v) for v in values], dtype=np.int32)


def _split_codes(splits: Sequence[str | None]) -> NDArray[np.int8]:
    order = {"train": 0, "val": 1, "test": 2}
    return np.array([order.get(s or "", -1) for s in splits], dtype=np.int8)


def _write_parquet(path: Path, table: pa.Table) -> None:
    buffer = io.BytesIO()
    pq.write_table(table, buffer, compression="zstd", use_dictionary=True)
    _replace(path, buffer.getvalue())


def pairs_table(
    features: FeatureSet, pairs: PairTable, ids: dict[str, list[str | None]]
) -> pa.Table:
    items = features.items
    sources = [item.source for item in items]
    images = [item.item_id for item in items]
    splits = [item.split for item in items]
    source_code = _codes(sources)
    cross_source = source_code[pairs.i] != source_code[pairs.j]
    split_code = _split_codes(splits)
    sa, sb = split_code[pairs.i], split_code[pairs.j]
    cross_split = ~cross_source & (sa >= 0) & (sb >= 0) & (sa != sb)
    categories = pa.DictionaryArray.from_arrays(
        pa.array(pairs.category.astype(np.int32)), pa.array(list(CATEGORIES))
    )
    return pa.table(
        {
            "source_a": _encoded(sources, pairs.i),
            "image_a": _encoded(images, pairs.i),
            "split_a": _encoded(splits, pairs.i),
            "source_b": _encoded(sources, pairs.j),
            "image_b": _encoded(images, pairs.j),
            "split_b": _encoded(splits, pairs.j),
            "sha256_equal": pa.array(pairs.sha_equal, type=pa.bool_()),
            "cosine": pa.array(pairs.cosine, type=pa.float32()),
            "phash_distance": pa.array(pairs.phash, type=pa.uint8()),
            "dhash_distance": pa.array(pairs.dhash, type=pa.uint8()),
            "category": categories,
            "decision": pa.DictionaryArray.from_arrays(
                pa.array(np.zeros(len(pairs.i), dtype=np.int32)), pa.array([DECISION])
            ),
            "cross_split": pa.array(np.asarray(cross_split, dtype=bool), type=pa.bool_()),
            "cross_source": pa.array(np.asarray(cross_source, dtype=bool), type=pa.bool_()),
            "group_near": _same_group(ids["near"], pairs.i, pairs.j),
            "group_family": _same_group(ids["family"], pairs.i, pairs.j),
        }
    )


def neighbours_table(features: FeatureSet, result: AnalysisResult) -> pa.Table:
    items = features.items
    n, k = result.neighbours.index.shape
    rows = np.repeat(np.arange(n, dtype=np.int64), k)
    cols = result.neighbours.index.reshape(-1).astype(np.int64)
    sources = [item.source for item in items]
    images = [item.item_id for item in items]
    splits = [item.split for item in items]
    source_code = _codes(sources)
    same_source = source_code[rows] == source_code[cols]
    split_code = _split_codes(splits)
    a, b = split_code[rows], split_code[cols]
    cross_split = same_source & (a >= 0) & (b >= 0) & (a != b)
    return pa.table(
        {
            "source": _encoded(sources, rows),
            "image": _encoded(images, rows),
            "split": _encoded(splits, rows),
            "rank": pa.array(np.tile(np.arange(1, k + 1, dtype=np.int16), n), type=pa.int16()),
            "neighbor_source": _encoded(sources, cols),
            "neighbor_image": _encoded(images, cols),
            "neighbor_split": _encoded(splits, cols),
            "cosine": pa.array(result.neighbours.cosine.reshape(-1), type=pa.float32()),
            "same_source": pa.array(np.asarray(same_source, dtype=bool), type=pa.bool_()),
            "cross_split": pa.array(np.asarray(cross_split, dtype=bool), type=pa.bool_()),
            "phash_distance": pa.array(
                np.bitwise_count(features.phash[rows] ^ features.phash[cols]).astype(np.uint8),
                type=pa.uint8(),
            ),
            "dhash_distance": pa.array(
                np.bitwise_count(features.dhash[rows] ^ features.dhash[cols]).astype(np.uint8),
                type=pa.uint8(),
            ),
            "group_family": _same_group(result.group_ids["family"], rows, cols),
        }
    )


def groups_table(rows: Sequence[GroupRow]) -> pa.Table:
    strings = pa.list_(pa.string())
    return pa.table(
        {
            "group_id": pa.array([r.group_id for r in rows], type=pa.string()),
            "level": pa.array([r.level for r in rows], type=pa.string()),
            "threshold": pa.array([r.threshold for r in rows], type=pa.float64()),
            "size": pa.array([len(r.members) for r in rows], type=pa.int32()),
            "members": pa.array([r.members for r in rows], type=strings),
            "sources": pa.array([r.sources for r in rows], type=strings),
            "splits": pa.array([r.splits for r in rows], type=strings),
            "n_annotations": pa.array([r.n_annotations for r in rows], type=pa.int32()),
            "max_similarity": pa.array([r.max_similarity for r in rows], type=pa.float64()),
            "min_similarity": pa.array([r.min_similarity for r in rows], type=pa.float64()),
            "mean_similarity": pa.array([r.mean_similarity for r in rows], type=pa.float64()),
            "n_edges": pa.array([r.n_edges for r in rows], type=pa.int64()),
            "min_edge_similarity": pa.array(
                [r.min_edge_similarity for r in rows], type=pa.float64()
            ),
            "cross_split": pa.array([r.cross_split for r in rows], type=pa.bool_()),
            "crosses": pa.array([r.crosses for r in rows], type=strings),
            "cross_source": pa.array([r.cross_source for r in rows], type=pa.bool_()),
            "n_keys": pa.array([r.n_keys for r in rows], type=pa.int32()),
        }
    )


def review_csv(
    features: FeatureSet, rows: Sequence[ReviewRow], ids: dict[str, list[str | None]]
) -> bytes:
    """The review queue; the two reviewer columns stay empty until a human fills them."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(REVIEW_COLUMNS)
    for row in rows:
        a, b = features.items[row.i], features.items[row.j]
        near_a, near_b = ids["near"][row.i], ids["near"][row.j]
        fam_a, fam_b = ids["family"][row.i], ids["family"][row.j]
        writer.writerow(
            [
                row.pair_id,
                row.stratum,
                row.suggested_category,
                f"{row.cosine:.6f}",
                row.phash_distance,
                row.dhash_distance,
                a.source,
                a.item_id,
                a.split or "",
                a.group or "",
                a.subgroup or "",
                b.source,
                b.item_id,
                b.split or "",
                b.group or "",
                b.subgroup or "",
                near_a if near_a is not None and near_a == near_b else "",
                fam_a if fam_a is not None and fam_a == fam_b else "",
                "",
                "",
            ]
        )
    return buffer.getvalue().encode("utf-8")


def read_review(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if rows and tuple(rows[0]) != REVIEW_COLUMNS:
        raise ValueError(f"{path.name}: unexpected columns")
    return rows


def read_groups(path: Path) -> list[dict[str, object]]:
    """The rows of ``leakage-groups.parquet`` as dictionaries."""
    rows: list[dict[str, object]] = pq.read_table(path).to_pylist()
    return rows


def write_audit(path: Path, audit: Audit) -> None:
    _replace(path, (audit.model_dump_json(indent=2) + "\n").encode("utf-8"))


def read_audit(path: Path) -> Audit:
    return Audit.model_validate_json(path.read_text(encoding="utf-8"))


def write_artifacts(out: Path, features: FeatureSet, result: AnalysisResult) -> dict[str, str]:
    """Write the three tables and the review queue; returns file name -> SHA-256."""
    _write_parquet(out / PAIRS, pairs_table(features, result.pairs, result.group_ids))
    _write_parquet(out / NEIGHBOURS, neighbours_table(features, result))
    _write_parquet(out / GROUPS, groups_table(result.group_rows))
    _replace(out / REVIEW, review_csv(features, result.review, result.group_ids))
    return {name: sha256_of(out / name) for name in (PAIRS, NEIGHBOURS, GROUPS, REVIEW)}
