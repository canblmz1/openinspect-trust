"""The committed ingest reports must agree with the committed manifests and with each other.

No data is needed: the reports are small JSON files in git. They were produced from the real archives
(see ``openinspect ingest run``); these tests keep them honest afterwards.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openinspect.ingest.report import CrossSource, SourceReport, render_markdown
from openinspect.provenance.registry import LoadedManifest, load_registry

REPO = Path(__file__).resolve().parents[2]
INGEST = REPO / "manifests" / "ingest"


def accepted() -> list[LoadedManifest]:
    return [lm for lm in load_registry(REPO).loaded if lm.manifest.usable_for_ingest]


def report_of(slug: str) -> SourceReport:
    return SourceReport.model_validate_json(
        (INGEST / slug / "report.json").read_text(encoding="utf-8")
    )


def test_every_accepted_source_has_a_report_and_a_download_record() -> None:
    slugs = {lm.manifest.slug for lm in accepted()}
    assert slugs == {"dspcbsd-plus", "pcb-ind", "pcb-defect"}
    for slug in slugs:
        assert (INGEST / slug / "report.json").is_file()
        assert (INGEST / slug / "download.json").is_file()


@pytest.mark.parametrize("item", accepted(), ids=lambda lm: lm.manifest.slug)
def test_a_report_agrees_with_its_manifest(item: LoadedManifest) -> None:
    manifest, slug = item.manifest, item.manifest.slug
    report = report_of(slug)
    (spec,) = manifest.acquisition.download_files
    assert manifest.acquisition.archive_sha256 == {spec.filename: report.archive.sha256}
    assert manifest.acquisition.download_date is not None
    assert manifest.acquisition.sha256_manifest == f"manifests/ingest/{slug}/report.json"
    assert report.archive.filename == spec.filename
    assert report.archive.bytes == spec.bytes
    assert report.archive.size_ok is True
    assert report.archive.checksum_ok is True
    assert report.archive.zip_crc_ok is True
    assert report.licence.spdx == manifest.licence.spdx
    assert report.licence.attribution_in_manifest is True
    assert (REPO / report.licence.manifest).is_file()
    assert report.images == manifest.content.image_count
    assert report.annotations == manifest.content.annotation_count
    assert report.decode.failed == 0
    assert [r for r in report.reconciliation if r.status == "mismatch"] == []


@pytest.mark.parametrize("item", accepted(), ids=lambda lm: lm.manifest.slug)
def test_the_class_counts_in_the_manifest_are_the_observed_ones(item: LoadedManifest) -> None:
    report = report_of(item.manifest.slug)
    observed = {c.label: c.count for c in report.classes}
    declared = {c.label: c.count for c in item.manifest.content.original_classes}
    assert declared == observed


@pytest.mark.parametrize("item", accepted(), ids=lambda lm: lm.manifest.slug)
def test_the_download_record_matches_the_archive_hash_in_the_manifest(item: LoadedManifest) -> None:
    record = json.loads((INGEST / item.manifest.slug / "download.json").read_text(encoding="utf-8"))
    (file,) = record["files"]
    assert {file["filename"]: file["sha256"]} == item.manifest.acquisition.archive_sha256
    assert file["size_ok"] is True
    assert file["checksum_ok"] is True


def test_the_markdown_report_is_exactly_what_the_json_reports_produce() -> None:
    slugs = sorted(lm.manifest.slug for lm in accepted())
    reports = [report_of(slug) for slug in slugs]
    cross = CrossSource.model_validate_json(
        (INGEST / "cross_source.json").read_text(encoding="utf-8")
    )
    committed = (REPO / "reports" / "m2-ingest-report.md").read_text(encoding="utf-8")
    assert committed == render_markdown(reports, cross)


def test_no_image_is_shared_between_sources() -> None:
    cross = CrossSource.model_validate_json(
        (INGEST / "cross_source.json").read_text(encoding="utf-8")
    )
    assert cross.sources == ["dspcbsd-plus", "pcb-defect", "pcb-ind"]
    assert cross.shared_sha256 == 0
    assert cross.images_per_source == {"dspcbsd-plus": 10259, "pcb-defect": 230, "pcb-ind": 4789}


def test_the_expected_findings_are_on_record() -> None:
    by_slug = {
        slug: {a.code for a in report_of(slug).anomalies} for slug in ("pcb-ind", "dspcbsd-plus")
    }
    assert {"voc_unreadable", "coco_missing_box", "box_out_of_bounds"} <= by_slug["pcb-ind"]
    assert "non_data_file_in_archive" in by_slug["dspcbsd-plus"]
    ind = report_of("pcb-ind")
    assert ind.grouping.quality == "explicit"
    assert report_of("dspcbsd-plus").grouping.quality == "none"
    assert report_of("pcb-defect").grouping.quality == "derived"
