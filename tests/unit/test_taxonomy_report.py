"""The M4 audit and its reports: a pure function of the audit and the taxonomy."""

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq

from openinspect.taxonomy.audit import M4Audit, M4Run, build_audit, spread
from openinspect.taxonomy.mapping import MappedImage
from openinspect.taxonomy.quality import Finding, NeighbourPair, all_findings
from openinspect.taxonomy.report import REPORTS, render_reports, write_reports
from openinspect.taxonomy.tables import MAP, MAP_COLUMNS, REVIEW, map_table, write_artifacts
from openinspect.validation import HumanValidation
from tests.taxonomy_helpers import DECLARED, box, mapped, taxonomy

RUN = M4Run(
    code_commit="0123456789abcdef",
    code_dirty=False,
    taxonomy_sha256="f" * 64,
    phash_max=4,
    near_threshold=0.95,
)
NOT_REVIEWED = HumanValidation(queue="artifacts/m3/review-candidates.csv", queued=300, reviewed=0)


def images() -> list[MappedImage]:
    return [
        mapped("src-a", "a1.png", [box(0, "SH", (1, 1, 11, 11)), box(1, "OP", (20, 20, 40, 30))]),
        mapped("src-a", "a2.png", [box(0, "SP", (1, 1, 9, 9)), box(1, "SH", (5, 5, 15, 15))]),
        mapped("src-a", "a3.png", [box(0, "OP", (1, 1, 1, 9))], split="val"),
        mapped("src-b", "b1.png", [box(0, "short", (1, 1, 21, 21))], size=(300, 300)),
        mapped("src-b", "b2.png", [box(0, "burr", (1, 1, 5, 5))], split=None),
        mapped("src-b", "b3.png", [], flags=("no_annotations",)),
        mapped("src-b", "b4.png", [box(0, "open", (2, 2, 30, 8))]),
    ]


def audit_for(validation: HumanValidation = NOT_REVIEWED) -> tuple[M4Audit, list[Finding]]:
    t = taxonomy()
    mapped_images = images()
    pairs = [NeighbourPair("src-a", "a1.png", "src-b", "b1.png", "NEAR_DUPLICATE", 0.97, 1, False)]
    findings, agreement = all_findings(mapped_images, t, pairs, phash_max=4)
    audit = build_audit(
        mapped_images,
        t,
        DECLARED,
        findings,
        agreement,
        run=RUN,
        inputs={"records/src-a/images.jsonl": "a" * 64},
        validation=validation,
    )
    return audit, findings


def test_the_audit_counts_eligibility_per_source() -> None:
    audit, findings = audit_for()
    rows = {s.source: s for s in audit.sources}
    a, b = rows["src-a"], rows["src-b"]
    assert (a.images, a.eligible_images, a.excluded_images, a.negatives) == (3, 2, 1, 0)
    assert a.excluded_by == {"SP": 1}
    assert a.benchmark_boxes_in_excluded == 1  # the SH box that goes with the excluded image
    assert a.eligible_by_split == {"train": 1, "val": 1}
    assert (b.images, b.eligible_images, b.excluded_images, b.negatives) == (4, 2, 1, 1)
    assert audit.benchmark_classes == ["short", "open"]
    labels = {(r.source, r.original_label): r for r in audit.labels}
    assert labels[("src-b", "placeholder")].boxes == 0
    assert not labels[("src-b", "placeholder")].declared
    assert labels[("src-a", "OP")].benchmark
    assert not labels[("src-b", "burr")].benchmark
    classes = {c.normalized_label: c for c in audit.classes}
    assert classes["spur"].candidate_of[0].original_label == "burr"
    geometry = {(g.normalized_label, g.source): g for g in audit.geometry}
    assert geometry[("short", "src-b")].boxes == 1
    assert geometry[("open", "src-a")].images == 2
    assert audit.review_rows == len(findings) > 0
    assert {e.signal for e in audit.examples} <= {f.signal for f in findings}


def test_spread() -> None:
    assert spread([]) is None
    s = spread([1.0, 2.0, 3.0])
    assert s is not None
    assert (s.n, s.median) == (3, 2.0)


def test_reports_answer_the_question_and_state_the_validation_status() -> None:
    audit, _ = audit_for()
    files = render_reports(audit, taxonomy())
    assert set(files) == set(REPORTS)
    overlap = files["class-overlap.md"]
    assert "**Answer.** 2 classes can be compared across all 2 independent sources" in overlap
    assert "`src-a` `OP` to `open`" in overlap  # the COMPATIBLE mapping is named
    assert "(candidate of AMBIGUOUS `burr`)" in overlap
    mapping = files["taxonomy-mapping.md"]
    assert "`placeholder` (not declared)" in mapping
    assert "## Reverse mapping" in mapping
    assert "## Candidate merges" in mapping
    quality = files["label-quality.md"]
    assert "**Human validation: NOT PERFORMED.** Reviewed pairs: 0 / 300" in quality
    assert "have not yet been independently human-validated" in quality
    assert "No label, box or image was changed or dropped" in quality
    assert "`0123456789ab`" in quality


def test_a_source_without_eligible_images_is_explained() -> None:
    t = taxonomy()
    only = [mapped("src-a", "a.png", [box(0, "SH", (1, 1, 5, 5)), box(1, "HB", (6, 6, 9, 9))])]
    audit = build_audit(
        only,
        t,
        DECLARED,
        [],
        [],
        run=RUN.model_copy(update={"code_commit": None}),
        inputs={},
        validation=HumanValidation(queue="q.csv", queued=2, reviewed=2),
    )
    files = render_reports(audit, t)
    assert "no whole image is eligible" in files["class-overlap.md"]
    assert "**Human validation: COMPLETE.**" in files["label-quality.md"]
    assert "Code: n/a" in files["label-quality.md"]
    assert "Shared by some sources but not all" not in files["class-overlap.md"]


def test_artifacts_and_reports_are_written_deterministically(tmp_path: Path) -> None:
    audit, findings = audit_for()
    t = taxonomy()
    mapped_images = images()
    first = write_artifacts(tmp_path / "a", mapped_images, t, findings)
    second = write_artifacts(tmp_path / "b", mapped_images, t, findings)
    assert first == second
    assert set(first) == {MAP, REVIEW}
    table = pq.read_table(tmp_path / "a" / MAP)
    assert tuple(table.column_names) == MAP_COLUMNS
    assert table.num_rows == sum(len(i.boxes) for i in mapped_images)
    rows = table.to_pylist()
    assert rows[0]["original_label"] == "SH"
    assert rows[0]["normalized_label"] == "short"
    assert {r["evidence"] for r in rows if r["original_label"] == "burr"} == {
        "'tiny burrs at edges', mostly at holes"
    }
    assert map_table([], t).num_rows == 0
    written = write_reports(tmp_path / "reports", audit, t)
    assert [p.name for p in written] == sorted(REPORTS)
