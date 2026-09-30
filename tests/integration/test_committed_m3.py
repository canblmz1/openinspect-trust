"""The committed M3 artifacts, reports and protocol must agree with each other.

No data is needed: ``artifacts/m3/audit.json`` holds every number of the reports and was produced
from the real images by ``openinspect dedup run --all``. These tests keep the committed files
honest afterwards, on every platform CI runs on.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from openinspect.dedup.audit_models import Audit, SyntheticRecall
from openinspect.dedup.report import render_reports
from openinspect.dedup.tables import (
    AUDIT,
    GROUPS,
    NEIGHBOURS,
    PAIRS,
    REVIEW,
    REVIEW_COLUMNS,
    SYNTHETIC_RECALL,
    THRESHOLDS,
    read_audit,
    read_review,
)
from openinspect.dedup.thresholds import PHASH_CAP, Thresholds
from openinspect.provenance.registry import load_registry

REPO = Path(__file__).resolve().parents[2]
ARTIFACTS = REPO / "artifacts" / "m3"
REPORTS = REPO / "reports" / "m3"
# docs/M3_PROTOCOL.md as committed in 8572b7e, before any leakage number was computed
PROTOCOL_SHA256 = "d70a130babcac45d650e8f0d5227546a5266d772e5932f21f422ba98de35102e"
TRACKED = (PAIRS, GROUPS, REVIEW, THRESHOLDS, SYNTHETIC_RECALL)


@pytest.fixture(scope="module")
def audit() -> Audit:
    return read_audit(ARTIFACTS / AUDIT)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_frozen_protocol_is_unchanged() -> None:
    assert sha256(REPO / "docs" / "M3_PROTOCOL.md") == PROTOCOL_SHA256
    assert (REPO / "docs" / "M3_PROTOCOL_AMENDMENT.md").is_file()


def test_the_reports_are_exactly_what_the_audit_renders(audit: Audit) -> None:
    expected = render_reports(audit)
    committed = {
        path.relative_to(REPORTS).as_posix(): path.read_text(encoding="utf-8")
        for path in REPORTS.rglob("*")
        if path.is_file()
    }
    assert set(committed) == set(expected)
    for name, text in expected.items():
        assert committed[name] == text, name


def test_tracked_artifacts_match_the_digests_in_the_audit(audit: Audit) -> None:
    assert set(audit.artifacts) == {*TRACKED, NEIGHBOURS}
    for name in TRACKED:
        assert sha256(ARTIFACTS / name) == audit.artifacts[name], name


def test_the_audit_covers_every_ingested_image(audit: Audit) -> None:
    accepted = {
        lm.manifest.slug: lm.manifest.content.image_count or 0
        for lm in load_registry(REPO).loaded
        if lm.manifest.usable_for_ingest
    }
    assert {s.source: s.images for s in audit.run.sources} == accepted
    assert audit.run.images == sum(accepted.values()) == 15278
    assert all(s.embedded == s.images for s in audit.run.sources)
    assert audit.run.failures == []
    assert audit.hash_audit.sha256_equal_pairs == 0  # as found by M2
    assert audit.cross_source.sha256_equal_pairs == 0


def test_the_numbers_come_from_committed_code_and_the_pinned_model(audit: Audit) -> None:
    commit = audit.run.code_commit
    assert commit is not None
    assert len(commit) == 40
    assert audit.run.code_dirty is False
    assert audit.run.model_id == "facebook/dinov2-small"
    assert audit.run.revision.startswith("ed25f3a31f01")
    assert (audit.run.preprocessing_version, audit.run.backend) == ("v1", "cpu-fp32")
    assert audit.run.seed == 0


def test_the_thresholds_follow_the_frozen_rule(audit: Audit) -> None:
    t = audit.thresholds
    ruled = [p for p in t.from_pools if p.used_in_rule]
    assert {(p.source, p.pool) for p in ruled} == {
        ("pcb-ind", "(batch, side)"),
        ("pcb-defect", "family A"),
    }
    family = max(p.family for p in ruled if p.family is not None)
    assert t.family == pytest.approx(family)
    assert t.review == pytest.approx(
        min(family, max(p.review for p in ruled if p.review is not None))
    )
    assert t.near == pytest.approx(max(family, min(s.near for s in t.from_synthetic)))
    assert t.phash_candidate == min(max(s.phash for s in t.from_synthetic), PHASH_CAP)
    assert {s.source: s.n_near for s in t.from_synthetic} == {
        "dspcbsd-plus": 1000,
        "pcb-defect": 1000,
        "pcb-ind": 1000,
    }
    for pool in t.from_pools:
        if pool.fallback is None:
            assert (pool.review, pool.family) == (pool.precision_050, pool.precision_090)


def test_a_group_aware_split_never_crosses_a_group(audit: Audit) -> None:
    for level in audit.levels:
        for source, rebuilt in level.reconstructed.items():
            if rebuilt is not None:
                assert rebuilt.groups_crossing == 0, (level.level, source)
                assert rebuilt.counts == rebuilt.ratios  # the official sizes are kept


def test_the_review_queue_is_complete_and_undecided(audit: Audit) -> None:
    rows = read_review(ARTIFACTS / REVIEW)
    assert 250 <= len(rows) <= 300
    assert len({row["pair_id"] for row in rows}) == len(rows)
    assert {row["human_decision"] for row in rows} == {""}
    assert {row["human_notes"] for row in rows} == {""}
    thresholds = audit.thresholds
    for row in rows:
        cosine = float(row["cosine"])
        if row["machine_category"] == "NEAR_DUPLICATE":
            assert cosine >= thresholds.near
        if row["machine_category"] == "BELOW_REVIEW":
            assert cosine < thresholds.review


def test_the_tables_decide_nothing_and_agree_with_the_audit(audit: Audit) -> None:
    pairs = pq.read_table(ARTIFACTS / PAIRS, columns=["decision", "category", "cross_split"])
    assert set(pairs.column("decision").to_pylist()) == {"review"}
    counted = sum(c.pairs for c in audit.categories)
    assert pairs.num_rows == counted
    groups = pq.read_table(ARTIFACTS / GROUPS).to_pylist()
    for row in groups:
        assert row["size"] == len(row["members"]) >= 2
        assert row["cross_split"] == bool(row["crosses"])
        assert row["all_pairs_min_similarity"] <= row["all_pairs_max_similarity"]
        assert row["chaining_gap"] == pytest.approx(
            row["edge_min_similarity"] - row["all_pairs_min_similarity"]
        )
        assert row["edge_min_similarity"] >= row["threshold"] - 1e-6
    for level in ("near", "family"):
        members = [m for row in groups if row["level"] == level for m in row["members"]]
        assert len(members) == len(set(members)), level  # a partition: no image in two groups


def test_the_json_artifacts_repeat_the_audit(audit: Audit) -> None:
    thresholds = Thresholds.model_validate_json((ARTIFACTS / THRESHOLDS).read_text("utf-8"))
    assert thresholds == audit.thresholds
    recall = json.loads((ARTIFACTS / SYNTHETIC_RECALL).read_text("utf-8"))
    assert [SyntheticRecall.model_validate(row) for row in recall] == audit.synthetic_recall
    assert {row.source for row in audit.synthetic_recall} == {
        "dspcbsd-plus",
        "pcb-defect",
        "pcb-ind",
    }
    for row in audit.synthetic_recall:
        assert row.final_near_threshold == audit.thresholds.near
        assert row.target_recall == 0.95
        assert row.meets_target == (row.achieved_recall >= row.target_recall)


def test_the_metadata_findings_of_ingest_are_reproduced(audit: Audit) -> None:
    rows = {(r.source, r.key): r for r in audit.metadata_integrity}
    batch = rows[("pcb-ind", "group_id")]
    assert (batch.values, batch.crossing) == (685, 125)  # M2: 125 of 685 batches in two splits
    side = rows[("pcb-ind", "subgroup_id")]
    assert (side.values, side.crossing) == (1069, 0)  # M2: no (batch, side) group is split
    assert all(r.source == "pcb-ind" for r in audit.metadata_integrity)  # the only keyed split


def test_provenance_and_assurance_inputs_are_complete(audit: Audit) -> None:
    assert [p.source for p in audit.provenance] == ["dspcbsd-plus", "pcb-defect", "pcb-ind"]
    for p in audit.provenance:
        assert p.evidence_ok is True
        assert p.archive_ok is True
        assert p.images_recorded == p.images_expected
    assert {s.source: s.acquisition_id for s in audit.run.sources} == {
        "dspcbsd-plus": "factory-aoi",
        "pcb-ind": "factory-aoi",
        "pcb-defect": "lab-flatbed-scan",
    }


def test_the_robustness_check_covers_every_source_and_level(audit: Audit) -> None:
    check = audit.robustness
    assert check is not None
    assert check.other_model == "facebook/dinov2-base@f9e44c814b77"
    assert {(r.source, r.level) for r in check.rows} == {
        (s, level)
        for s in ("dspcbsd-plus", "pcb-defect", "pcb-ind")
        for level in ("near", "family")
    }
    assert (
        check.other_thresholds.review
        <= check.other_thresholds.family
        <= check.other_thresholds.near
    )
    assert set(check.top1_agreement) == {"dspcbsd-plus", "pcb-defect", "pcb-ind"}


def test_the_review_queue_is_stratified_four_ways() -> None:
    rows = read_review(ARTIFACTS / REVIEW)
    assert tuple(rows[0]) == REVIEW_COLUMNS
    for row in rows:
        scope, band, split, key = row["stratum"].split("|")
        assert band == row["machine_category"]
        assert split in {"cross-split", "same-split", "no-split"}
        assert key in {"same-group", "other-group", "no-key"}
        assert scope in {"across", f"within:{row['source_a']}"}
    assert any(row["stratum"].endswith("|cross-split|other-group") for row in rows)


def test_every_component_reports_its_chaining() -> None:
    names = pq.read_schema(ARTIFACTS / GROUPS).names
    for column in (
        "size",
        "edge_min_similarity",
        "edge_mean_similarity",
        "all_pairs_min_similarity",
        "all_pairs_mean_similarity",
        "chaining_gap",
    ):
        assert column in names
