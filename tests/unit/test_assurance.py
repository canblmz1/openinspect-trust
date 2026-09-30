"""The dimensional assurance report: every status follows its rule and carries its evidence."""

from __future__ import annotations

from pathlib import Path

import pytest

from openinspect.assurance import (
    NO_EVIDENCE,
    NOT_ASSESSABLE,
    OPTIMISTIC,
    RULES,
    assess,
    collect_provenance,
)
from openinspect.dedup.analysis import run_analysis
from openinspect.dedup.audit_models import Audit, SourceProvenance
from tests.conftest import Repo
from tests.dedup_helpers import REPO_ROOT, clustered_features, make_spec, repository_settings
from tests.factories import accepted_manifest

SOURCES = ("dspcbsd-plus", "pcb-defect", "pcb-ind")
DIMENSIONS = [
    "Provenance coverage",
    "Licence evidence",
    "Archive integrity",
    "Exact duplicates",
    "Visual similarity leakage",
    "Group split integrity",
]


def provenance(source: str, **changes: object) -> SourceProvenance:
    base = SourceProvenance(
        source=source,
        licence="CC-BY-4.0",
        evidence_files=3,
        evidence_ok=True,
        archive_ok=True,
        images_expected=10,
        images_recorded=10,
        acquisition_id={"pcb-defect": "scanner"}.get(source, "line"),
    )
    return base.model_copy(update=changes)


@pytest.fixture(scope="module")
def audit() -> Audit:
    clustered = clustered_features()
    result = run_analysis(
        clustered.features,
        clustered.synthetic,
        spec=make_spec(dim=16),
        weights_sha256="0" * 64,
        settings=repository_settings(permutations=100, resamples=100),
    )
    return result.audit.model_copy(update={"provenance": [provenance(s) for s in SOURCES]})


def test_every_source_gets_every_dimension_with_evidence(audit: Audit) -> None:
    report = assess(audit)
    assert [s.source for s in report.sources] == list(SOURCES)
    for source in report.sources:
        assert [d.name for d in source.dimensions] == DIMENSIONS
        assert all(d.evidence for d in source.dimensions)
    assert set(RULES) >= set(DIMENSIONS)
    by = {s.source: s for s in report.sources}
    # a planted cross-split cluster: a warning, never a failure
    assert by["dspcbsd-plus"].status("Visual similarity leakage") == "WARNING"
    assert by["dspcbsd-plus"].status("Group split integrity") == "MISSING"  # no key
    assert by["dspcbsd-plus"].status("Exact duplicates") == "WARNING"  # identical, same split
    assert by["dspcbsd-plus"].assessment == OPTIMISTIC
    # batch 0005 has one side in train and one in val
    assert by["pcb-ind"].status("Group split integrity") == "FAIL"
    assert "Group split integrity" in by["pcb-ind"].reasons
    assert by["pcb-defect"].assessment == NOT_ASSESSABLE
    assert by["pcb-defect"].status("Visual similarity leakage") == "N/A"
    assert by["pcb-defect"].reasons == []
    assert report.assessment == OPTIMISTIC
    pool = {d.name: d for d in report.pool}
    assert pool["Independent source validation"].status == "MISSING"
    assert pool["Source diversity"].status == "LOW"  # two acquisition kinds
    assert "scanner (pcb-defect)" in pool["Source diversity"].evidence[0]


def test_statuses_follow_their_rules(audit: Audit) -> None:
    changed = audit.model_copy(
        update={
            "provenance": [
                provenance("dspcbsd-plus", archive_ok=False),
                provenance("pcb-ind", images_recorded=9, evidence_ok=False),
            ]
        }
    )
    by = {s.source: s for s in assess(changed).sources}
    assert by["dspcbsd-plus"].status("Archive integrity") == "FAIL"
    assert by["pcb-ind"].status("Provenance coverage") == "FAIL"
    assert by["pcb-ind"].status("Licence evidence") == "FAIL"
    assert all(d.status == "MISSING" for d in by["pcb-defect"].dimensions[:3])  # no record
    unknown = audit.model_copy(
        update={"provenance": [provenance("pcb-ind", archive_ok=None, images_recorded=None)]}
    )
    ind = next(s for s in assess(unknown).sources if s.source == "pcb-ind")
    assert ind.status("Archive integrity") == "MISSING"
    assert ind.status("Provenance coverage") == "MISSING"
    none = audit.model_copy(update={"provenance": []})
    pool = {d.name: d.status for d in assess(none).pool}
    assert pool["Source diversity"] == "MISSING"


def test_a_clean_split_is_not_called_optimistic(audit: Audit) -> None:
    levels = []
    for level in audit.levels:
        leakage = [
            leak.model_copy(
                update={
                    "groups_crossing_any": 0,
                    "eval_neighbour": [
                        n.model_copy(update={"with_train_neighbour": 0})
                        for n in leak.eval_neighbour
                    ],
                }
            )
            for leak in level.leakage
        ]
        levels.append(level.model_copy(update={"leakage": leakage}))
    categories = [
        c.model_copy(update={"pairs": 0, "cross_split": 0})
        if c.category == "EXACT_DUPLICATE"
        else c
        for c in audit.categories
    ]
    clean = audit.model_copy(
        update={
            "levels": levels,
            "categories": categories,
            "metadata_integrity": [
                m.model_copy(update={"crossing": 0}) for m in audit.metadata_integrity
            ],
        }
    )
    by = {s.source: s for s in assess(clean).sources}
    assert by["pcb-ind"].status("Visual similarity leakage") == "PASS"
    assert by["pcb-ind"].status("Group split integrity") == "PASS"
    assert by["pcb-ind"].assessment == NO_EVIDENCE
    duplicated = [
        c.model_copy(update={"pairs": 2, "cross_split": 1})
        if c.category == "EXACT_DUPLICATE" and c.scope == "within:pcb-ind"
        else c
        for c in categories
    ]
    worse = clean.model_copy(update={"categories": duplicated})
    ind = next(s for s in assess(worse).sources if s.source == "pcb-ind")
    assert ind.status("Exact duplicates") == "FAIL"
    assert ind.assessment == OPTIMISTIC


def test_provenance_is_read_from_the_repository() -> None:
    rows = collect_provenance(REPO_ROOT, list(SOURCES), {"pcb-ind": "factory-aoi"})
    assert [r.source for r in rows] == list(SOURCES)
    for row in rows:
        assert row.licence == "CC-BY-4.0"
        assert row.evidence_ok is True
        assert row.archive_ok is True
        assert row.images_recorded == row.images_expected
    assert {r.source: r.acquisition_id for r in rows}["pcb-ind"] == "factory-aoi"


def test_provenance_without_an_ingest_report(repo: Repo) -> None:
    repo.write_manifest(accepted_manifest("demo-source"))
    (row,) = collect_provenance(repo.root, ["demo-source", "unknown"], {})
    assert row.archive_ok is None
    assert row.images_recorded is None
    assert row.evidence_ok is True


def test_the_repository_root_is_what_the_helpers_use() -> None:
    assert (REPO_ROOT / "configs" / "dedup.yaml").is_file()
    assert Path(__file__).resolve().is_relative_to(REPO_ROOT)
