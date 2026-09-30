from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from openinspect.ingest.manifest_patch import ManifestPatchError, set_acquisition_fields
from openinspect.ingest.report import (
    AdapterInfo,
    Anomaly,
    ArchiveCheck,
    ClassCount,
    CrossSource,
    DecodeInfo,
    DuplicateInfo,
    GroupingInfo,
    LicenceTrace,
    Reconciliation,
    SourceReport,
    SplitCount,
    render_markdown,
    write_json,
)
from openinspect.provenance.registry import parse_manifest_text

MANIFEST = """\
# a curated manifest: comments must survive
schema_version: 1
slug: demo-source
dataset_name: "Demo"
status: pending
acquisition:
  download_method: http   # how
  download_files: []
  download_date: null
  archive_sha256: null
  sha256_manifest: null
content:
  domain: demo
"""


def write(tmp_path: Path, text: str = MANIFEST) -> Path:
    path = tmp_path / "demo-source.yaml"
    path.write_text(text, encoding="utf-8")
    return path


# ------------------------------------------------------------------------ manifest_patch


def test_acquisition_fields_are_filled_and_comments_survive(tmp_path: Path) -> None:
    path = write(tmp_path)
    changed = set_acquisition_fields(
        path,
        download_date=date(2026, 9, 30),
        archive_sha256={"b.zip": "b" * 64, "a.zip": "a" * 64},
        sha256_manifest="manifests/ingest/demo-source/report.json",
    )
    assert changed
    text = path.read_text(encoding="utf-8")
    assert "# a curated manifest: comments must survive" in text
    assert "  download_method: http   # how" in text
    assert "  download_date: 2026-09-30" in text
    assert f'  archive_sha256: {{"a.zip": "{"a" * 64}", "b.zip": "{"b" * 64}"}}' in text
    manifest, issues = parse_manifest_text(text)
    assert issues == []
    assert manifest is not None
    assert manifest.acquisition.download_date == date(2026, 9, 30)
    assert manifest.acquisition.archive_sha256 == {"a.zip": "a" * 64, "b.zip": "b" * 64}
    assert manifest.acquisition.sha256_manifest == "manifests/ingest/demo-source/report.json"


def test_patching_twice_with_the_same_values_changes_nothing(tmp_path: Path) -> None:
    path = write(tmp_path)
    set_acquisition_fields(path, download_date=date(2026, 9, 30))
    before = path.read_bytes()
    assert set_acquisition_fields(path, download_date=date(2026, 9, 30)) is False
    assert path.read_bytes() == before


def test_a_field_that_is_already_set_differently_is_never_overwritten(tmp_path: Path) -> None:
    path = write(tmp_path)
    set_acquisition_fields(path, download_date=date(2026, 9, 30))
    with pytest.raises(ManifestPatchError, match="already set"):
        set_acquisition_fields(path, download_date=date(2026, 10, 1))


def test_a_manifest_without_the_block_or_field_is_refused(tmp_path: Path) -> None:
    no_block = write(tmp_path, "schema_version: 1\nslug: demo-source\n")
    with pytest.raises(ManifestPatchError, match="no top-level 'acquisition:' block"):
        set_acquisition_fields(no_block, download_date=date(2026, 9, 30))
    no_field = write(tmp_path, MANIFEST.replace("  download_date: null\n", ""))
    with pytest.raises(ManifestPatchError, match="download_date not found"):
        set_acquisition_fields(no_field, download_date=date(2026, 9, 30))


def test_an_invalid_result_is_not_written(tmp_path: Path) -> None:
    path = write(tmp_path)
    before = path.read_bytes()
    with pytest.raises(ManifestPatchError, match="invalid"):
        set_acquisition_fields(path, sha256_manifest="../escape.json")
    assert path.read_bytes() == before


# --------------------------------------------------------------------------------- report


def make_report(
    slug: str = "demo-source", *, anomalies: list[Anomaly] | None = None
) -> SourceReport:
    return SourceReport(
        slug=slug,
        dataset_name="Demo dataset",
        archive=ArchiveCheck(
            filename="demo.zip",
            bytes=1234,
            size_ok=True,
            checksum_algo="md5",
            checksum_ok=True,
            sha256="a" * 64,
            files_extracted=12,
        ),
        adapter=AdapterInfo(
            name="demo",
            version=1,
            status="ok",
            canonical_format="coco",
            formats_present=["coco", "yolo"],
        ),
        images=10,
        annotations=25,
        decode=DecodeInfo(images=10, decodable=10, failed=0),
        classes=[
            ClassCount(label="short", label_id=0, count=15),
            ClassCount(label="spur", label_id=1, count=10),
        ],
        splits=[
            SplitCount(split="train", images=8, annotations=20, images_without_annotations=1),
            SplitCount(split="val", images=2, annotations=5, images_without_annotations=0),
        ],
        grouping=GroupingInfo(
            key="batch",
            quality="explicit",
            n_groups=3,
            summary="names carry the batch",
            evidence=["3 batches"],
        ),
        exact_duplicates=DuplicateInfo(groups=0, redundant_files=0, cross_split_groups=0),
        anomalies=anomalies or [],
        reconciliation=[
            Reconciliation(
                field="content.image_count", manifest="10", observed="10", status="match"
            ),
            Reconciliation(
                field="content.image_size_px.min", manifest=None, observed="[1, 1]", status="new"
            ),
        ],
        licence=LicenceTrace(
            manifest=f"manifests/sources/{slug}.yaml",
            spdx="CC-BY-4.0",
            licence_url="https://creativecommons.org/licenses/by/4.0/",
            attribution_in_manifest=True,
            evidence_files=3,
            archive_says=["README says: use the Zenodo licence"],
        ),
        digests={"images_jsonl": "b" * 64},
        notes=["a note"],
    )


def test_json_reports_are_deterministic_and_round_trip(tmp_path: Path) -> None:
    report = make_report()
    write_json(tmp_path / "a" / "report.json", report)
    write_json(tmp_path / "b.json", report)
    assert (tmp_path / "a" / "report.json").read_bytes() == (tmp_path / "b.json").read_bytes()
    text = (tmp_path / "b.json").read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert "\r" not in text
    assert json.loads(text)["slug"] == "demo-source"
    assert SourceReport.model_validate_json(text) == report


def test_the_markdown_report_has_the_requested_table_and_details() -> None:
    anomalies = [
        Anomaly(
            code="voc_unreadable", severity="warning", message="m", count=1, examples=["x.xml"]
        ),
        Anomaly(code="info_only", severity="info", message="i", count=2),
    ]
    cross = CrossSource(
        sources=["demo-source"], images_per_source={"demo-source": 10}, shared_sha256=0
    )
    text = render_markdown([make_report(anomalies=anomalies)], cross)
    header = (
        "| source | images | annotations | classes | original splits | identifiable grouping key "
        "| anomalies | adapter status |"
    )
    assert header in text
    row = next(line for line in text.splitlines() if line.startswith("| `demo-source`"))
    assert "| 10 | 25 |" in row
    assert "2: short 15 · spur 10" in row
    assert "train 8 / val 2" in row
    assert "batch (explicit)" in row
    assert (
        "voc_unreadable ×1; info_only ×2" in row
    )  # worst first; info-level findings are listed too
    assert "canonical: coco" in row
    assert "Cross-source exact duplicates" in text
    assert "**0**" in text
    assert "`voc_unreadable` ×1" in text
    assert "e.g. `x.xml`" in text
    assert "licence traceability" in text
    assert "README says: use the Zenodo licence" in text
    assert "| content.image_count | 10 | 10 | match |" in text


def test_a_source_without_splits_says_so() -> None:
    report = make_report().model_copy(update={"splits": []})
    assert "none shipped" in render_markdown([report], None)


def test_a_source_without_a_grouping_key_or_anomalies_says_none() -> None:
    grouping = make_report().grouping.model_copy(update={"key": None, "quality": "none"})
    report = make_report().model_copy(update={"grouping": grouping})
    row = next(
        line
        for line in render_markdown([report], None).splitlines()
        if line.startswith("| `demo-source`")
    )
    cells = [c.strip() for c in row.strip("|").split("|")]
    assert cells[5] == "none"  # grouping key: no "(none)" quality suffix
    assert cells[6] == "none"  # anomalies


def test_a_yaml_block_value_counts_as_already_set(tmp_path: Path) -> None:
    block = "  archive_sha256:\n    a.zip: " + "a" * 64 + "\n"
    text = MANIFEST.replace("  archive_sha256: null\n", block)
    path = write(tmp_path, text)
    before = path.read_bytes()
    with pytest.raises(ManifestPatchError, match="already set"):
        set_acquisition_fields(path, archive_sha256={"a.zip": "b" * 64})
    assert path.read_bytes() == before
