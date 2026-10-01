"""``openinspect release``: build, check, report, smoke and export on a small synthetic world."""

from __future__ import annotations

import csv
import io
import json
import zipfile
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq
import pytest
import yaml
from typer.testing import Result

from openinspect.release.export import data_yaml, verify_zip, yolo_labels, zip_bytes
from openinspect.release.manifest import ITEMS, RELEASE, read_manifest
from openinspect.release.verify import verify_release
from tests.conftest import Repo
from tests.release_helpers import build_world


@pytest.fixture
def world(repo: Repo, tmp_path: Path) -> tuple[Repo, Path]:
    data = tmp_path / "data"
    build_world(repo.root, data)
    return repo, data


def run(repo: Repo, data: Path, *args: str) -> Result:
    return repo.cli("release", *args, "--data-dir", str(data))


def test_build_check_report_smoke_and_export(world: tuple[Repo, Path]) -> None:
    repo, data = world
    built = run(repo, data, "build")
    assert built.exit_code == 0, built.output
    output = built.output
    assert "release v0.1: 27 images" in output
    assert "src-a 11, src-b 11, src-c 5" in output
    assert "A1:" in output
    assert "supplied groups crossing 0" in output
    folder = repo.root / "manifests" / "releases" / "v0.1"
    manifest = read_manifest(folder / RELEASE)
    assert {i.id: i.status for i in manifest.invariants} == {f"I{k}": "PASS" for k in range(1, 10)}
    assert manifest.counts.by_source == {"src-a": 11, "src-b": 11, "src-c": 5}
    assert manifest.generated_by.code_commit is None
    assert manifest.m3_limitations.human_validation.status == "NOT PERFORMED"
    names = {e.name for e in manifest.splits}
    assert names == {"A0", "A1", "B-src-a", "B-src-b", "B-src-c"}
    fold = next(e for e in manifest.splits if e.name == "B-src-b")
    assert fold.counts["excluded"] == 2  # a00 and a01 share a similarity component with b00
    rows = pq.read_table(folder / ITEMS).to_pylist()
    crops = [r for r in rows if r["crop_x_min"] is not None]
    assert len(crops) == 5
    assert {r["file_name"][-4:] for r in crops} == {".png"}
    assert all(r["sha256_pixels"] for r in crops)
    images = data / "release" / "v0.1" / "images"
    assert sorted(p.name for p in images.iterdir()) == sorted(r["file_name"] for r in rows)
    assert (repo.root / "reports" / "m5" / "release.md").is_file()
    assert any(
        note.startswith("B-src-b: 2 `src-a` items share a constraint") for note in manifest.notes
    )

    checked = repo.cli("release", "check")
    assert checked.exit_code == 0, checked.output
    assert "invariants I1 PASS" in checked.output

    report = repo.root / "reports" / "m5" / "release.md"
    first = report.read_bytes()
    report.write_text("stale", encoding="utf-8")
    again = repo.cli("release", "report")
    assert again.exit_code == 0, again.output
    assert report.read_bytes() == first

    smoke = run(repo, data, "smoke")
    assert smoke.exit_code == 0, smoke.output
    target = folder / "evren-smoke"
    record = json.loads((target / "smoke.json").read_text(encoding="utf-8"))
    assert record["items"] == 4
    assert record["counts"] == {"train": 2, "val": 1, "test": 1}
    expected = list(
        csv.DictReader(io.StringIO((target / "expected-splits.csv").read_text(encoding="utf-8")))
    )
    assert Counter(r["split"] for r in expected) == Counter({"train": 2, "val": 1, "test": 1})
    package = data / "exports" / "v0.1" / "openinspect-trust-v0.1-evren-smoke-yolo.zip"
    assert verify_zip(package, record["members"]) == []
    with zipfile.ZipFile(package) as archive:
        listed = archive.namelist()
        assert "data.yaml" in listed
        for row in expected:
            assert f"images/{row['split']}/{row['file_name']}" in listed
            assert f"labels/{row['split']}/{row['global_id']}.txt" in listed
    smoke_again = run(repo, data, "smoke")
    assert smoke_again.exit_code == 0
    assert (
        json.loads((target / "smoke.json").read_text(encoding="utf-8"))["zip_sha256"]
        == record["zip_sha256"]
    )

    exported = run(repo, data, "export", "--scheme", "B-src-b")
    assert exported.exit_code == 0, exported.output
    full = data / "exports" / "v0.1" / "openinspect-trust-v0.1-B-src-b-yolo.zip"
    sidecar = json.loads(full.with_suffix(".json").read_text(encoding="utf-8"))
    assert sidecar["items"] == 27
    with zipfile.ZipFile(full) as archive:
        assert not any("excluded" in name for name in archive.namelist())
    unknown = run(repo, data, "export", "--scheme", "B-nowhere")
    assert unknown.exit_code == 1
    assert "no split scheme" in unknown.output


def test_check_finds_tampering(world: tuple[Repo, Path]) -> None:
    repo, data = world
    assert run(repo, data, "build").exit_code == 0
    split = repo.root / "manifests" / "splits" / "v0.1" / "A1__seed0.csv"
    split.write_text(
        split.read_text(encoding="utf-8").replace(",train", ",test", 1), encoding="utf-8"
    )
    broken = repo.cli("release", "check")
    assert broken.exit_code == 1
    assert "A1__seed0.csv does not match its SHA-256" in broken.output
    manifest, problems = verify_release(repo.root, "v0.1")
    assert manifest is not None
    assert problems
    (repo.root / "configs" / "taxonomy.yaml").write_text(
        (repo.root / "configs" / "taxonomy.yaml").read_text(encoding="utf-8") + "# x\n",
        encoding="utf-8",
    )
    _, problems = verify_release(repo.root, "v0.1")
    assert any("taxonomy changed" in p for p in problems)
    assert verify_release(repo.root, "v9.9")[0] is None


def test_smoke_needs_images_that_match_the_manifest(world: tuple[Repo, Path]) -> None:
    repo, data = world
    assert run(repo, data, "build").exit_code == 0
    for image in (data / "release" / "v0.1" / "images").iterdir():
        image.write_bytes(b"changed")
    failed = run(repo, data, "smoke")
    assert failed.exit_code == 1
    assert "differs from the release manifest" in failed.output


def test_build_and_report_fail_cleanly(world: tuple[Repo, Path]) -> None:
    repo, data = world
    missing = repo.cli("release", "report")
    assert missing.exit_code == 1
    assert "cannot read release.json" in missing.output
    no_check = repo.cli("release", "check")
    assert no_check.exit_code == 1
    config = repo.root / "configs" / "release.yaml"
    raw = yaml.safe_load(config.read_text(encoding="utf-8"))
    raw["size"] = {"min": 1000, "max": 5000}
    config.write_text(yaml.safe_dump(raw), encoding="utf-8")
    small = run(repo, data, "build")
    assert small.exit_code == 1
    assert "the release needs 1000" in small.output
    config.write_text("schema_version: 7\n", encoding="utf-8")
    invalid = repo.cli("release", "check")
    assert invalid.exit_code == 1
    assert "invalid configs/release.yaml" in invalid.output


def test_yolo_helpers() -> None:
    from openinspect.release.export import ExportBox, ExportItem

    item = ExportItem(
        "OI_s_000000000000",
        "OI_s_000000000000.jpg",
        "0" * 64,
        "s",
        200,
        100,
        ("short",),
        (ExportBox(0, (10.0, 20.0, 50.0, 60.0)),),
        {"A1": "train"},
    )
    assert yolo_labels(item) == "0 0.150000 0.400000 0.200000 0.400000\n"
    text = data_yaml(["short", "open"], "title")
    assert "nc: 2" in text
    assert "  1: open" in text
    first = zip_bytes([("a.txt", b"1"), ("b/c.txt", b"2")])
    assert first == zip_bytes([("a.txt", b"1"), ("b/c.txt", b"2")])


def test_verify_zip_reports_differences(tmp_path: Path) -> None:
    path = tmp_path / "p.zip"
    path.write_bytes(zip_bytes([("a.txt", b"1"), ("extra.txt", b"3")]))
    import hashlib

    expected = {"a.txt": hashlib.sha256(b"2").hexdigest(), "gone.txt": "0" * 64}
    assert verify_zip(path, expected) == [
        "missing gone.txt",
        "unexpected extra.txt",
        "a.txt differs",
    ]
