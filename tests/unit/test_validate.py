from __future__ import annotations

from typing import Any

import pytest

from openinspect.provenance.licences import LicenceAllowlist, load_allowlist
from openinspect.provenance.registry import Issue, Registry, load_registry
from openinspect.provenance.validate import sha256_file, validate_manifest, validate_registry
from tests.conftest import Repo
from tests.factories import (
    EVIDENCE_REL,
    EVIDENCE_SHA,
    accepted_manifest,
    pending_manifest,
    rejected_manifest,
    with_value,
)

EXTRA_EVIDENCE = "manifests/evidence/extra/notes.json"


def _registry(repo: Repo, *manifests: dict[str, Any]) -> Registry:
    for data in manifests:
        repo.write_manifest(data)
    return load_registry(repo.root)


def _allowlist(repo: Repo) -> LicenceAllowlist:
    return load_allowlist(repo.root / "configs" / "licences.yaml")


def _validate(repo: Repo, registry: Registry, **options: Any) -> list[Issue]:
    return validate_registry(registry, _allowlist(repo), **options)


def _codes(issues: list[Issue]) -> list[str]:
    return [issue.code for issue in issues]


# -------------------------------------------------------------------- allowlist


def test_a_clean_accepted_source_has_no_issues(repo: Repo) -> None:
    assert _validate(repo, _registry(repo, accepted_manifest())) == []


@pytest.mark.parametrize(
    ("spdx", "fragment"),
    [
        ("MIT", "not on the allowlist"),
        ("CC-BY-NC-4.0", "non-commercial"),
        ("CC-BY-SA-4.0", "share-alike"),
    ],
)
def test_an_accepted_licence_outside_the_allowlist_is_an_error(
    repo: Repo, spdx: str, fragment: str
) -> None:
    registry = _registry(repo, with_value(accepted_manifest(), "licence.spdx", spdx))
    issues = _validate(repo, registry)
    assert _codes(issues) == ["E_LICENCE_NOT_ALLOWED"]
    assert fragment in issues[0].message


def test_pending_and_rejected_sources_skip_the_allowlist(repo: Repo) -> None:
    pending = with_value(pending_manifest(), "licence", {"spdx": "CC-BY-NC-4.0"})
    rejected = with_value(rejected_manifest(), "licence", {"spdx": "MIT"})
    assert _validate(repo, _registry(repo, pending, rejected), check_evidence=False) == []


# ---------------------------------------------------------------- public release


def test_unknown_redistribution_is_a_warning_internally_and_an_error_for_a_public_release(
    repo: Repo,
) -> None:
    registry = _registry(repo, with_value(accepted_manifest(), "licence.redistribution", "unclear"))
    internal = _validate(repo, registry)
    assert _codes(internal) == ["W_PUBLIC_RELEASE_BLOCKED"]
    assert internal[0].level == "warning"
    public = _validate(repo, registry, release="public")
    assert _codes(public) == ["E_PUBLIC_RELEASE_BLOCKED"]
    assert public[0].level == "error"
    assert "redistribution is unclear" in public[0].message


def test_denied_derivative_work_blocks_a_public_release(repo: Repo) -> None:
    registry = _registry(
        repo, with_value(accepted_manifest(), "licence.derivative_work", "not_allowed")
    )
    issues = _validate(repo, registry, release="public")
    assert "derivative_work is not_allowed" in issues[0].message


def test_pending_and_rejected_sources_never_block_a_public_release(repo: Repo) -> None:
    registry = _registry(repo, accepted_manifest(), pending_manifest(), rejected_manifest())
    assert _validate(repo, registry, release="public", check_evidence=False) == []


def test_validate_manifest_is_pure_and_needs_no_disk(repo: Repo) -> None:
    registry = _registry(repo, accepted_manifest())
    manifest = registry.loaded[0].manifest
    assert validate_manifest(manifest, allowlist=_allowlist(repo)) == []


# -------------------------------------------------------------------- evidence


def test_a_tampered_evidence_file_is_detected_twice(repo: Repo) -> None:
    registry = _registry(repo, accepted_manifest())
    (repo.root / EVIDENCE_REL).write_bytes(b"tampered")
    codes = _codes(_validate(repo, registry))
    assert "E_EVIDENCE_HASH_MISMATCH" in codes
    assert "E_EVIDENCE_INDEX_MISMATCH" in codes


def test_a_missing_evidence_file_is_an_error(repo: Repo) -> None:
    registry = _registry(repo, accepted_manifest())
    (repo.root / EVIDENCE_REL).unlink()
    codes = _codes(_validate(repo, registry))
    assert "E_EVIDENCE_MISSING_FILE" in codes
    assert "E_EVIDENCE_INDEX_ORPHAN" in codes


def test_a_missing_index_is_an_error_when_manifests_use_evidence(repo: Repo) -> None:
    registry = _registry(repo, accepted_manifest())
    (repo.root / "manifests" / "evidence" / "SHA256SUMS.txt").unlink()
    assert _codes(_validate(repo, registry)) == ["E_EVIDENCE_INDEX_MISSING"]


def test_evidence_that_is_not_in_the_index_is_an_error(repo: Repo) -> None:
    registry = _registry(repo, accepted_manifest())
    (repo.root / "manifests" / "evidence" / "SHA256SUMS.txt").write_text("", encoding="ascii")
    codes = _codes(_validate(repo, registry))
    assert "E_EVIDENCE_NOT_INDEXED" in codes
    assert "W_EVIDENCE_UNINDEXED" in codes


def test_an_index_entry_without_a_file_is_an_error(repo: Repo) -> None:
    registry = _registry(repo, accepted_manifest())
    index = repo.root / "manifests" / "evidence" / "SHA256SUMS.txt"
    index.write_text(
        index.read_text(encoding="ascii") + f"{EVIDENCE_SHA}  ghost/file.json\n", encoding="ascii"
    )
    issues = _validate(repo, registry)
    assert _codes(issues) == ["E_EVIDENCE_INDEX_ORPHAN"]
    assert "ghost/file.json" in issues[0].message


def test_a_malformed_index_line_is_an_error(repo: Repo) -> None:
    registry = _registry(repo, accepted_manifest())
    index = repo.root / "manifests" / "evidence" / "SHA256SUMS.txt"
    index.write_text(index.read_text(encoding="ascii") + "not a hash line\n", encoding="ascii")
    assert "E_EVIDENCE_INDEX_MALFORMED" in _codes(_validate(repo, registry))


def test_an_indexed_file_that_no_manifest_uses_is_a_warning(repo: Repo) -> None:
    registry = _registry(repo, accepted_manifest())
    extra = repo.root / EXTRA_EVIDENCE
    extra.parent.mkdir(parents=True)
    extra.write_bytes(b"{}")
    index = repo.root / "manifests" / "evidence" / "SHA256SUMS.txt"
    index.write_text(
        index.read_text(encoding="ascii") + f"{sha256_file(extra)}  extra/notes.json\n",
        encoding="ascii",
    )
    issues = _validate(repo, registry)
    assert _codes(issues) == ["W_EVIDENCE_UNREFERENCED"]
    assert issues[0].level == "warning"


def test_evidence_checks_can_be_switched_off(repo: Repo) -> None:
    registry = _registry(repo, accepted_manifest())
    (repo.root / EVIDENCE_REL).write_bytes(b"tampered")
    assert _validate(repo, registry, check_evidence=False) == []


# ------------------------------------------------------------------ selection


def test_an_unknown_slug_is_an_error(repo: Repo) -> None:
    registry = _registry(repo, accepted_manifest())
    issues = _validate(repo, registry, only=["nope"])
    assert _codes(issues) == ["E_UNKNOWN_SLUG"]


def test_validating_one_source_ignores_problems_of_the_others(repo: Repo) -> None:
    registry = _registry(
        repo,
        accepted_manifest(),
        with_value(accepted_manifest("other-source"), "licence.spdx", "MIT"),
    )
    assert _codes(_validate(repo, registry)) == ["E_LICENCE_NOT_ALLOWED"]
    assert _validate(repo, registry, only=["demo-source"]) == []


def test_registry_load_issues_are_part_of_the_result(repo: Repo) -> None:
    (repo.sources / "broken.yaml").write_text("a: [1", encoding="utf-8")
    assert "E_YAML" in _codes(_validate(repo, load_registry(repo.root), check_evidence=False))
