"""The committed release v0.1, its split files, its report and the EVREN smoke package agree.

No data is needed: everything is checked from ``manifests/releases/v0.1``, ``manifests/splits/v0.1``,
the configuration, the taxonomy and the committed M3 artifacts.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from openinspect.files import sha256_file
from openinspect.release.config import load_release_config
from openinspect.release.manifest import ITEMS, RELEASE, ReleaseManifest, read_manifest
from openinspect.release.report import REPORT, render
from openinspect.release.verify import release_dir, verify_release
from openinspect.taxonomy.config import load_taxonomy
from openinspect.validation import read_validation

REPO = Path(__file__).resolve().parents[2]
VERSION = load_release_config(REPO).version
FOLDER = release_dir(REPO, VERSION)
SMOKE = FOLDER / "evren-smoke"


@pytest.fixture(scope="module")
def manifest() -> ReleaseManifest:
    return read_manifest(FOLDER / RELEASE)


def test_the_release_checks_out_from_its_files() -> None:
    _, problems = verify_release(REPO, VERSION)
    assert problems == []


def test_the_report_is_what_the_manifest_renders(manifest: ReleaseManifest) -> None:
    committed = (REPO / "reports" / "m5" / REPORT).read_text(encoding="utf-8")
    assert committed == render(manifest)


def test_the_release_meets_the_specification(manifest: ReleaseManifest) -> None:
    config = load_release_config(REPO)
    assert config.size.min <= manifest.counts.images <= config.size.max
    assert all(s.share <= config.max_source_share + 1e-9 for s in manifest.sources)
    assert 3 <= len(manifest.taxonomy.benchmark_classes) <= 5
    assert manifest.taxonomy.benchmark_classes == load_taxonomy(REPO).benchmark_classes
    assert {i.id: i.status for i in manifest.invariants} == {f"I{k}": "PASS" for k in range(1, 10)}
    assert manifest.generated_by.code_dirty is False
    assert manifest.m3_limitations.human_validation.model_dump() == read_validation(REPO).record()


def test_group_aware_and_source_held_out_splits_cross_no_group(manifest: ReleaseManifest) -> None:
    by_name = {e.name: e for e in manifest.splits}
    assert set(by_name) == {"A0", "A1", *(f"B-{s.source}" for s in manifest.sources)}
    for name, entry in by_name.items():
        if name == "A0":
            assert entry.measure.supplied_groups_crossing > 0  # the naive split, measured
            continue
        assert entry.measure.supplied_groups_crossing == 0, name
        assert entry.measure.primary_pairs_crossing == 0, name
        assert entry.measure.sha256_crossing == 0, name


def test_the_smoke_package_was_recorded_before_upload(manifest: ReleaseManifest) -> None:
    record = json.loads((SMOKE / "smoke.json").read_text(encoding="utf-8"))
    config = load_release_config(REPO)
    assert record["counts"] == config.smoke.counts
    assert record["scheme"] == config.smoke.scheme
    assert record["release_manifest_sha256"] == sha256_file(FOLDER / RELEASE)
    assert record["classes"] == {
        str(k): c for k, c in enumerate(manifest.taxonomy.benchmark_classes)
    }
    rows = {r["global_id"]: r for r in pq.read_table(FOLDER / ITEMS).to_pylist()}
    expected = list(
        csv.DictReader(io.StringIO((SMOKE / "expected-splits.csv").read_text(encoding="utf-8")))
    )
    assert len(expected) == sum(config.smoke.counts.values()) == record["items"]
    for row in expected:
        item = rows[row["global_id"]]
        assert row["split"] == item[f"split_{record['scheme']}"]
        assert row["sha256"] == item["sha256"]
        assert record["members"][f"images/{row['split']}/{row['file_name']}"] == item["sha256"]
        assert f"labels/{row['split']}/{row['global_id']}.txt" in record["members"]
    assert set(record["members"]) == {
        "data.yaml",
        *(f"images/{r['split']}/{r['file_name']}" for r in expected),
        *(f"labels/{r['split']}/{r['global_id']}.txt" for r in expected),
    }
    for split, count in config.smoke.counts.items():
        assert sum(1 for r in expected if r["split"] == split) == count
