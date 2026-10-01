"""The committed M4 artifacts and reports must agree with each other, the taxonomy and ingest.

No data is needed: ``artifacts/m4/audit.json`` and ``taxonomy-map.parquet`` were produced from the
real records by ``openinspect taxonomy audit --all``; these tests keep the committed files honest.
"""

from __future__ import annotations

import csv
import hashlib
import io
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from openinspect.ingest.report import SourceReport
from openinspect.provenance.registry import load_registry
from openinspect.taxonomy.audit import M4Audit
from openinspect.taxonomy.config import (
    COMPARABLE,
    TAXONOMY_PATH,
    check_against_sources,
    load_taxonomy,
)
from openinspect.taxonomy.quality import COLUMNS
from openinspect.taxonomy.report import render_reports
from openinspect.taxonomy.tables import AUDIT, MAP, REVIEW, read_audit
from openinspect.validation import read_validation

REPO = Path(__file__).resolve().parents[2]
ARTIFACTS = REPO / "artifacts" / "m4"
REPORTS = REPO / "reports" / "m4"


@pytest.fixture(scope="module")
def audit() -> M4Audit:
    return read_audit(ARTIFACTS / AUDIT)


@pytest.fixture(scope="module")
def rows() -> list[dict[str, object]]:
    table: list[dict[str, object]] = pq.read_table(ARTIFACTS / MAP).to_pylist()
    return table


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ingest_report(slug: str) -> SourceReport:
    path = REPO / "manifests" / "ingest" / slug / "report.json"
    return SourceReport.model_validate_json(path.read_text(encoding="utf-8"))


def test_the_reports_are_exactly_what_the_audit_renders(audit: M4Audit) -> None:
    expected = render_reports(audit, load_taxonomy(REPO))
    committed = {p.name: p.read_text(encoding="utf-8") for p in REPORTS.iterdir() if p.is_file()}
    assert set(committed) == set(expected)
    for name, text in expected.items():
        assert committed[name] == text, name


def test_the_audit_used_the_committed_taxonomy_and_m3_artifacts(audit: M4Audit) -> None:
    assert sha256(REPO / TAXONOMY_PATH) == audit.run.taxonomy_sha256
    assert audit.run.code_dirty is False
    for name in ("duplicate-pairs.parquet", "thresholds.json"):
        key = f"artifacts/m3/{name}"
        assert audit.inputs[key] == sha256(REPO / key), name
    assert audit.human_validation == read_validation(REPO)


def test_tracked_artifacts_match_the_digests_in_the_audit(audit: M4Audit) -> None:
    assert set(audit.artifacts) == {MAP, REVIEW}
    for name, digest in audit.artifacts.items():
        assert sha256(ARTIFACTS / name) == digest, name


def test_original_labels_are_exactly_those_ingest_counted(
    audit: M4Audit, rows: list[dict[str, object]]
) -> None:
    counted = Counter((str(r["source_id"]), str(r["original_label"])) for r in rows)
    for source in audit.sources:
        report = ingest_report(source.source)
        expected = {(source.source, c.label): c.count for c in report.classes if c.count}
        assert {k: v for k, v in counted.items() if k[0] == source.source} == expected
        assert source.boxes == report.annotations
        assert source.images == report.images


def test_every_row_carries_its_mapping(rows: list[dict[str, object]]) -> None:
    taxonomy = load_taxonomy(REPO)
    benchmark = set(taxonomy.benchmark_classes)
    for row in rows:
        mapping = taxonomy.mapping(str(row["source_id"]), str(row["original_label"]))
        assert row["normalized_label"] == mapping.normalized_label
        assert row["mapping_status"] == mapping.status
        assert row["evidence"] == mapping.evidence
        assert row["benchmark_class"] == (
            mapping.status in COMPARABLE and mapping.normalized_label in benchmark
        )


def test_eligibility_follows_the_whole_image_rule(
    audit: M4Audit, rows: list[dict[str, object]]
) -> None:
    by_image: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        by_image[(str(row["source_id"]), str(row["image_id"]))].append(row)
    for boxes in by_image.values():
        whole = all(bool(b["benchmark_class"]) for b in boxes)
        assert {b["image_eligibility"] for b in boxes} == {"eligible" if whole else "excluded"}
    for source in audit.sources:
        images = [k for k in by_image if k[0] == source.source]
        eligible = [k for k in images if by_image[k][0]["image_eligibility"] == "eligible"]
        assert len(eligible) == source.eligible_images
        assert len(images) + source.negatives == source.images


def test_the_review_queue_never_decides(audit: M4Audit) -> None:
    text = (ARTIFACTS / REVIEW).read_text(encoding="utf-8")
    reader = csv.DictReader(io.StringIO(text))
    assert tuple(reader.fieldnames or ()) == COLUMNS
    queue = list(reader)
    assert len(queue) == audit.review_rows
    assert {r["status"] for r in queue} == {"REVIEW_REQUIRED"}
    assert {r["human_decision"] for r in queue} == {""}
    assert {r["human_notes"] for r in queue} == {""}
    assert [r["review_id"] for r in queue] == [f"LQ-{k:05d}" for k in range(1, len(queue) + 1)]
    expected: Counter[str] = Counter()
    for count in audit.signals:
        expected[count.signal] += count.findings
    assert Counter(r["signal"] for r in queue) == expected


def test_the_taxonomy_covers_every_source() -> None:
    registry = load_registry(REPO)
    accepted = [lm.manifest for lm in registry.loaded if lm.manifest.usable_for_ingest]
    declared = {m.slug: [c.label for c in m.content.original_classes] for m in accepted}
    used = {m.slug: [c.label for c in ingest_report(m.slug).classes if c.count] for m in accepted}
    assert check_against_sources(load_taxonomy(REPO), declared, used) == []
