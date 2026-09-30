"""The manifests and evidence that are committed to this repository must themselves be valid."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from openinspect.provenance.licences import load_allowlist
from openinspect.provenance.registry import load_registry, parse_manifest_text
from openinspect.provenance.validate import validate_registry

REPO = Path(__file__).resolve().parents[2]


def test_committed_manifests_pass_the_strictest_validation() -> None:
    registry = load_registry(REPO)
    allowlist = load_allowlist(REPO / "configs" / "licences.yaml")
    issues = validate_registry(registry, allowlist, release="public")
    assert issues == [], [issue.message for issue in issues]


def test_the_expected_sources_and_statuses_are_registered() -> None:
    registry = load_registry(REPO)
    statuses = {item.manifest.slug: item.manifest.status for item in registry.loaded}
    assert statuses == {
        "dspcbsd-plus": "accepted",
        "pcb-ind": "accepted",
        "pcb-defect": "accepted",
        "deeppcb": "rejected",
    }


def test_every_accepted_source_is_cc_by_4_and_releasable() -> None:
    for item in load_registry(REPO).loaded:
        if item.manifest.status == "accepted":
            assert item.manifest.licence.spdx == "CC-BY-4.0"
            assert item.manifest.public_release_allowed


def test_deeppcb_stays_rejected_with_its_conflict_documented() -> None:
    deeppcb = load_registry(REPO).get("deeppcb")
    assert deeppcb is not None
    manifest = deeppcb.manifest
    assert manifest.status == "rejected"
    assert not manifest.usable_for_ingest
    assert manifest.licence.conflicts
    assert manifest.decision.reason is not None
    assert "DO NOT USE" in manifest.decision.reason


def test_the_template_is_a_valid_pending_manifest() -> None:
    text = (REPO / "manifests" / "sources" / "_template.yaml").read_text(encoding="utf-8")
    manifest, issues = parse_manifest_text(text, "_template.yaml")
    assert issues == []
    assert manifest is not None
    assert manifest.status == "pending"


def _load_hash_script() -> ModuleType:
    path = REPO / "scripts" / "hash_evidence.py"
    spec = importlib.util.spec_from_file_location("hash_evidence", path)
    if spec is None or spec.loader is None:  # pragma: no cover
        pytest.fail("cannot load scripts/hash_evidence.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_evidence_index_is_exactly_what_the_hash_script_produces() -> None:
    expected: str = _load_hash_script().build_index()
    committed = (REPO / "manifests" / "evidence" / "SHA256SUMS.txt").read_bytes().decode("ascii")
    assert committed == expected
