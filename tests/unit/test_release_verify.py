"""``verify_release`` catches every broken invariant, even when the hashes were updated to match."""

from __future__ import annotations

import csv
import io
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from openinspect.files import sha256_file
from openinspect.release.manifest import ANNOTATIONS, ITEMS, RELEASE, read_manifest, write_manifest
from openinspect.release.verify import verify_release
from tests.conftest import Repo
from tests.release_helpers import build_world

Rows = list[dict[str, Any]]


@pytest.fixture
def built(repo: Repo, tmp_path: Path) -> Path:
    data = tmp_path / "data"
    build_world(repo.root, data)
    result = repo.cli("release", "build", "--data-dir", str(data))
    assert result.exit_code == 0, result.output
    assert verify_release(repo.root, "v0.1")[1] == []
    return repo.root


def forge(
    root: Path,
    rows_change: Callable[[Rows], None] | None = None,
    boxes_change: Callable[[Rows], None] | None = None,
    csv_change: Callable[[str, list[list[str]]], None] | None = None,
    manifest_change: Callable[[dict[str, Any]], None] | None = None,
) -> list[str]:
    """Apply a change, then make every hash in the manifest agree with it, and verify."""
    folder = root / "manifests" / "releases" / "v0.1"
    manifest = read_manifest(folder / RELEASE)
    rows: Rows = pq.read_table(folder / ITEMS).to_pylist()
    boxes: Rows = pq.read_table(folder / ANNOTATIONS).to_pylist()
    if rows_change:
        rows_change(rows)
    if boxes_change:
        boxes_change(boxes)
    pq.write_table(pa.Table.from_pylist(rows), folder / ITEMS)
    pq.write_table(pa.Table.from_pylist(boxes), folder / ANNOTATIONS)
    data = manifest.model_dump(mode="json")
    data["files"][ITEMS] = sha256_file(folder / ITEMS)
    data["files"][ANNOTATIONS] = sha256_file(folder / ANNOTATIONS)
    for entry in data["splits"]:
        table = [
            ["id", "split"],
            *sorted([r["global_id"], r[f"split_{entry['name']}"]] for r in rows),
        ]
        if csv_change:
            csv_change(entry["name"], table)
        buffer = io.StringIO()
        csv.writer(buffer, lineterminator="\n").writerows(table)
        path = root / entry["file"]
        path.write_text(buffer.getvalue(), encoding="utf-8")
        entry["sha256"] = sha256_file(path)
    if manifest_change:
        manifest_change(data)
    write_manifest(folder / RELEASE, type(manifest).model_validate(data))
    return verify_release(root, "v0.1")[1]


def _row(rows: Rows, image: str, index: int = 0) -> dict[str, Any]:
    return [r for r in rows if r["source_item_id"] == image][index]


def _other(split: str) -> str:
    return "val" if split != "val" else "train"


def test_the_forge_itself_changes_nothing(built: Path) -> None:
    assert forge(built) == []


def test_metadata_groups_similarity_components_and_crop_parents(built: Path) -> None:
    def cut_batch(rows: Rows) -> None:
        row = _row(rows, "b01.png")
        row["split_A1"] = _other(_row(rows, "b02.png")["split_A1"])
        row["canonical_split"] = row["split_A1"]

    assert any(
        p.startswith("I4: a metadata group crosses a split of A1") for p in forge(built, cut_batch)
    )


def test_similarity_component(built: Path) -> None:
    def cut(rows: Rows) -> None:
        _row(rows, "a03.png")["split_A1"] = _other(_row(rows, "a02.png")["split_A1"])

    assert any(p.startswith("I5:") for p in forge(built, cut))


def test_crop_parent(built: Path) -> None:
    def cut(rows: Rows) -> None:
        crops = [
            r for r in rows if r["source_item_id"] == "c1.png" or r["source_item_id"] == "c0.png"
        ]
        first = [r for r in crops if r["source_item_id"] == "c0.png"]
        first[0]["split_A1"] = _other(first[1]["split_A1"])

    problems = forge(built, cut)
    assert any(p.startswith("crop parents cross a split of A1") for p in problems)


def test_source_held_out_fold(built: Path) -> None:
    def leak(rows: Rows) -> None:
        _row(rows, "a05.png")["split_B-src-b"] = "test"

    assert any(p.startswith("I1: B-src-b mixes sources") for p in forge(built, leak))


def test_same_bytes_in_two_splits(built: Path) -> None:
    def copy(rows: Rows) -> None:
        a, b = _row(rows, "a05.png"), _row(rows, "a07.png")
        b["sha256"] = a["sha256"]
        b["split_A0"] = _other(a["split_A0"])

    assert any(
        p.startswith("I2: a file SHA-256 occurs in two splits of A0") for p in forge(built, copy)
    )


def test_provenance_licence_and_classes(built: Path) -> None:
    def blank(rows: Rows) -> None:
        _row(rows, "a05.png")["source_url"] = ""
        _row(rows, "a07.png")["licence"] = "GPL-3.0-only"

    problems = forge(built, blank)
    assert "I7: an item lacks a provenance field" in problems
    assert "I8: a licence is not on the allowlist" in problems

    def relabel(boxes: Rows) -> None:
        boxes[0]["normalized_label"] = "spur"

    assert any(p.startswith("I9:") for p in forge(built, boxes_change=relabel))


def test_ids_counts_and_split_files(built: Path) -> None:
    def rename(rows: Rows) -> None:
        rows[0]["global_id"] = "not-an-id"

    problems = forge(built, rename)
    assert "global ids are not unique or not well formed" in problems

    def count(data: dict[str, Any]) -> None:
        data["counts"]["images"] += 1

    assert "the item or box counts differ from the manifest" in forge(built, manifest_change=count)


def test_split_files_must_match_the_items(built: Path) -> None:
    def drop(name: str, table: list[list[str]]) -> None:
        if name == "A0":
            del table[1]

    assert any(
        "does not list exactly the released items" in p for p in forge(built, csv_change=drop)
    )

    def rename_split(name: str, table: list[list[str]]) -> None:
        if name == "A1":
            table[1][1] = "holdout"

    problems = forge(built, csv_change=rename_split)
    assert any("uses an unknown split name" in p for p in problems)
    assert any("disagrees with items.parquet" in p for p in problems)


def test_m3_pairs_and_failed_invariants_in_the_manifest(built: Path) -> None:
    pairs = built / "artifacts" / "m3" / "duplicate-pairs.parquet"
    pairs.write_bytes(pairs.read_bytes() + b"x")

    def fail_one(data: dict[str, Any]) -> None:
        data["invariants"][0]["status"] = "FAIL"

    problems = forge(built, manifest_change=fail_one)
    assert any("differs from the one the release was built with" in p for p in problems)
    assert "I1 is FAIL in the manifest" in problems
    (built / "configs" / "licences.yaml").write_text("not: [valid", encoding="utf-8")
    assert any(p.startswith("I8:") for p in forge(built))
