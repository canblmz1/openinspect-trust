"""The committed M5.5 and M6 outputs agree with the committed inputs (no data directory needed)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from openinspect.readiness.check import check_committed
from openinspect.readiness.models import Readiness
from openinspect.readiness.pipeline import verdict
from openinspect.readiness.report import render_all
from openinspect.release.config import load_release_config
from openinspect.release.manifest import ANNOTATIONS
from openinspect.release.smoke_record import (
    OBSERVED,
    SmokeRecord,
    build_checks,
    load_expected,
    load_observation,
    render,
)
from openinspect.release.verify import release_dir
from openinspect.validation import read_validation

REPO = Path(__file__).resolve().parents[2]
VERSION = load_release_config(REPO).version
SMOKE = release_dir(REPO, VERSION) / "evren-smoke"
VERDICTS = ("TRAINING READY WITH EXPLICIT LIMITATIONS", "NOT TRAINING READY", "TRAINING READY")
FORBIDDEN = (
    "confirmed duplicate",
    "confirmed leakage",
    "same physical board",
    "human-validated leakage",
)


@pytest.fixture(scope="module")
def readiness() -> Readiness:
    return Readiness.model_validate_json(
        (REPO / "artifacts" / "m5_5" / "readiness.json").read_text(encoding="utf-8")
    )


@pytest.fixture(scope="module")
def smoke() -> SmokeRecord:
    return SmokeRecord.model_validate_json(
        (REPO / "artifacts" / "m6" / "evren-smoke-test.json").read_text(encoding="utf-8")
    )


# --------------------------------------------------------------------------------- M6


def test_the_m6_record_follows_from_the_observations_and_the_committed_expectation(
    smoke: SmokeRecord,
) -> None:
    observed = load_observation(SMOKE / OBSERVED)
    expected = load_expected(SMOKE, release_dir(REPO, VERSION) / ANNOTATIONS)
    rederived = build_checks(observed, expected)
    committed = [c for c in smoke.checks if c.status == "OBSERVED_IN_EVREN"]
    assert committed == rederived
    assert smoke.verdict == "PASS"
    assert smoke.zip_check is not None
    assert smoke.zip_check.matches_record
    assert (
        smoke.expected_zip_sha256
        == json.loads((SMOKE / "smoke.json").read_text(encoding="utf-8"))["zip_sha256"]
    )


def test_the_m6_report_is_what_the_record_renders(smoke: SmokeRecord) -> None:
    text = (REPO / "reports" / "m6" / "evren-smoke-test.md").read_text(encoding="utf-8")
    assert text == render(smoke, SMOKE.relative_to(REPO).as_posix())


def test_the_m6_record_keeps_platform_health_and_assurance_apart(smoke: SmokeRecord) -> None:
    text = (REPO / "reports" / "m6" / "evren-smoke-test.md").read_text(encoding="utf-8")
    assert "not an OpenInspect-Trust assurance result" in text
    assert {s.status for s in smoke.statements} >= {"NOT_TESTED", "UNKNOWN"}


# ------------------------------------------------------------------------------- M5.5


def test_every_m5_5_output_rederives_from_committed_files(readiness: Readiness) -> None:
    assert check_committed(REPO, readiness) == []


def test_the_verdict_follows_its_rule(readiness: Readiness) -> None:
    assert readiness.verdict == verdict(readiness.blockers, readiness.limitations)
    report = (REPO / "reports" / "m5_5" / "TRAINING_READINESS.md").read_text(encoding="utf-8")
    section = report.split("## Verdict", 1)[1].split("##", 1)[0]
    found = [v for v in VERDICTS if f"**{v}**" in section]
    assert found == [readiness.verdict]
    assert len(readiness.answers) == 12


def test_the_reports_are_what_readiness_json_renders(readiness: Readiness) -> None:
    for path, text in render_all(readiness).items():
        assert (REPO / path).read_text(encoding="utf-8") == text, path


def test_every_report_states_the_human_validation(readiness: Readiness) -> None:
    status = read_validation(REPO)
    assert readiness.human_validation == status.record()
    for path in render_all(readiness):
        text = (REPO / path).read_text(encoding="utf-8")
        assert f"**Human validation: {status.status}.**" in text, path


def test_no_report_claims_what_was_not_validated(readiness: Readiness) -> None:
    for path in [*render_all(readiness), "reports/m6/evren-smoke-test.md"]:
        text = (REPO / path).read_text(encoding="utf-8").lower()
        text = re.sub(r"not allowed:[^.]*\.", "", text)  # the list of forbidden claims itself
        assert not [w for w in FORBIDDEN if w in text], path


def test_the_controlled_designs_hold_their_invariants(readiness: Readiness) -> None:
    for design in readiness.designs:
        by = {c.name: c for c in design.conditions}
        assert by["C1"].exposed_test_items == 0
        assert by["C1"].measure.supplied_groups_crossing == 0
        assert by["C1"].measure.primary_pairs_crossing == 0
        assert by["C0"].exposed_test_items == sum(design.probes.values()) > 0
        assert by["C0"].items["test"] == by["C1"].items["test"]
        assert by["C0"].items["val"] == by["C1"].items["val"]
        assert design.train_items_equal_by_source


def test_both_held_out_regimes_keep_source_integrity(readiness: Readiness) -> None:
    folds = {(h.regime, h.fold) for h in readiness.held_out}
    sources = sorted(readiness.negatives.available)
    assert folds == {(r, s) for r in ("B-strict", "B-natural") for s in sources}
    for h in readiness.held_out:
        assert h.pure
        assert h.test_sources == [h.fold]
        if h.regime == "B-natural":
            assert h.excluded == 0


def test_m5_5_changed_nothing_of_m3_m4_m5(readiness: Readiness) -> None:
    for prefix in ("artifacts/m3/", "artifacts/m4/", "manifests/releases/", "manifests/splits/"):
        assert any(path.startswith(prefix) for path in readiness.provenance.inputs), prefix
    assert not [
        p
        for p in readiness.provenance.outputs
        if p.startswith(("artifacts/m3", "artifacts/m4", "manifests/releases", "manifests/splits"))
    ]
