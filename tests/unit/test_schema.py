from __future__ import annotations

import re
from datetime import date

import pytest
from pydantic import ValidationError

from openinspect.provenance.schema import SourceManifest
from tests.factories import accepted_manifest, pending_manifest, rejected_manifest, with_value

# ------------------------------------------------------------------ accepted sources


def test_valid_accepted_manifest_is_accepted() -> None:
    manifest = SourceManifest.model_validate(accepted_manifest())
    assert manifest.status == "accepted"
    assert manifest.usable_for_ingest
    assert manifest.public_release_allowed
    assert manifest.public_release_blockers() == []
    assert manifest.identity.published_on == date(2026, 1, 1)


def test_missing_licence_is_rejected() -> None:
    data = with_value(accepted_manifest(), "licence.spdx", None)
    with pytest.raises(ValidationError, match=re.escape("licence.spdx is missing")):
        SourceManifest.model_validate(data)


def test_missing_source_url_is_rejected() -> None:
    data = with_value(accepted_manifest(), "identity.official_url", None)
    with pytest.raises(ValidationError, match=re.escape("identity.official_url is missing")):
        SourceManifest.model_validate(data)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("licence.licence_url", None, "licence.licence_url is missing"),
        ("licence.redistribution", None, "licence.redistribution is unanswered"),
        ("licence.derivative_work", None, "licence.derivative_work is unanswered"),
        ("licence.commercial_use", None, "licence.commercial_use is unanswered"),
        ("licence.attribution_required", None, "licence.attribution_required is unanswered"),
        ("licence.attribution_text", None, "licence.attribution_text is missing"),
        (
            "licence.changes_must_be_indicated",
            None,
            "licence.changes_must_be_indicated is unanswered",
        ),
        ("licence.verified_on", None, "licence.verified_on is missing"),
        ("licence.evidence", [], "licence.evidence has no archived entry"),
        ("identity.creators", [], "identity.creators is empty"),
        ("identity.version", None, "identity.version is missing"),
        ("identity.is_original_upload", False, "identity.is_original_upload must be true"),
        ("decision.decided_by", None, "decision.decided_by is missing"),
        ("decision.decided_on", None, "decision.decided_on is missing"),
        ("decision.reason", None, "decision.reason is missing"),
        ("decision.evidence", [], "decision.evidence is empty"),
        ("decision.status", "rejected", "decision.status must be 'accepted'"),
    ],
)
def test_accepted_source_requires_every_admission_field(
    field: str, value: object, message: str
) -> None:
    with pytest.raises(ValidationError, match=re.escape(message)):
        SourceManifest.model_validate(with_value(accepted_manifest(), field, value))


def test_all_problems_are_reported_together() -> None:
    data = with_value(
        with_value(accepted_manifest(), "licence.spdx", None), "identity.creators", []
    )
    with pytest.raises(ValidationError) as error:
        SourceManifest.model_validate(data)
    text = str(error.value)
    assert "licence.spdx is missing" in text
    assert "identity.creators is empty" in text


def test_decision_evidence_must_be_archived_licence_evidence() -> None:
    data = with_value(accepted_manifest(), "decision.evidence", ["manifests/evidence/other/x.json"])
    with pytest.raises(ValidationError, match="not archived licence evidence"):
        SourceManifest.model_validate(data)


def test_evidence_path_and_hash_go_together() -> None:
    entry = {
        "kind": "repository_record_api",
        "url": "https://example.org/record",
        "retrieved_on": date(2026, 9, 30),
        "archived_path": "manifests/evidence/a.json",
    }
    data = with_value(accepted_manifest(), "licence.evidence", [entry])
    with pytest.raises(ValidationError, match="archived_path and sha256 must be set together"):
        SourceManifest.model_validate(data)


# ------------------------------------------------------------- pending and rejected


def test_pending_manifest_needs_only_the_basics() -> None:
    manifest = SourceManifest.model_validate(pending_manifest())
    assert manifest.status == "pending"
    assert not manifest.usable_for_ingest
    assert manifest.public_release_blockers() == ["status is pending, not accepted"]


def test_pending_source_cannot_carry_a_decision_status() -> None:
    data = with_value(pending_manifest(), "decision", {"status": "accepted"})
    with pytest.raises(ValidationError, match="still pending"):
        SourceManifest.model_validate(data)


def test_rejected_source_is_valid_with_a_reason() -> None:
    manifest = SourceManifest.model_validate(rejected_manifest())
    assert manifest.status == "rejected"
    assert not manifest.usable_for_ingest
    assert manifest.public_release_blockers() == ["status is rejected, not accepted"]


def test_rejected_source_requires_a_reason() -> None:
    data = with_value(rejected_manifest(), "decision.reason", None)
    with pytest.raises(ValidationError, match=re.escape("decision.reason is missing")):
        SourceManifest.model_validate(data)


# ---------------------------------------------------------------- value formats


@pytest.mark.parametrize(
    "doi",
    [
        "https://doi.org/10.5281/zenodo.1",
        "doi:10.5281/zenodo.1",
        "10.5281",
        "zenodo.1",
        "10.5281/ space",
        "",
    ],
)
def test_invalid_doi_is_a_validation_error(doi: str) -> None:
    data = with_value(accepted_manifest(), "identity.doi", doi)
    with pytest.raises(ValidationError, match="invalid DOI"):
        SourceManifest.model_validate(data)


@pytest.mark.parametrize(
    "doi",
    [
        "10.5281/zenodo.19723114",
        "10.6084/m9.figshare.24970329.v1",
        "10.17632/vdj74sngvn.1",
        "10.1038/s41597-024-03656-8",
        "10.1016/j.dib.2025.112296",
    ],
)
def test_the_dois_of_real_records_are_valid(doi: str) -> None:
    manifest = SourceManifest.model_validate(with_value(accepted_manifest(), "identity.doi", doi))
    assert manifest.identity.doi == doi


def test_paper_doi_is_checked_too() -> None:
    data = with_value(accepted_manifest(), "identity.paper_doi", "not-a-doi")
    with pytest.raises(ValidationError, match="invalid DOI"):
        SourceManifest.model_validate(data)


@pytest.mark.parametrize(
    "url", ["ftp://example.org/x", "example.org", "http://", "https:// spaced.org"]
)
def test_invalid_urls_are_rejected(url: str) -> None:
    data = with_value(accepted_manifest(), "identity.official_url", url)
    with pytest.raises(ValidationError, match="invalid URL"):
        SourceManifest.model_validate(data)


@pytest.mark.parametrize(
    "slug",
    [
        "ab",
        "Upper-Case",
        "under_score",
        "-leading",
        "trailing-",
        "double--hyphen",
        "x" * 49,
        "a b c",
    ],
)
def test_invalid_slugs_are_rejected(slug: str) -> None:
    with pytest.raises(ValidationError, match="invalid slug"):
        SourceManifest.model_validate(with_value(pending_manifest(), "slug", slug))


@pytest.mark.parametrize("slug", ["abc", "dspcbsd-plus", "pcb-ind", "a1-b2-c3", "x" * 48])
def test_valid_slugs_are_accepted(slug: str) -> None:
    assert SourceManifest.model_validate(with_value(pending_manifest(), "slug", slug)).slug == slug


@pytest.mark.parametrize(
    "path",
    ["../secret.json", "/etc/passwd", "C:/evidence/x.json", "manifests\\evidence\\x.json", ""],
)
def test_evidence_paths_must_be_relative_posix_paths(path: str) -> None:
    data = with_value(accepted_manifest(), "decision.evidence", [path])
    with pytest.raises(ValidationError, match="invalid repository path"):
        SourceManifest.model_validate(data)


def test_unknown_keys_are_rejected() -> None:
    data = with_value(accepted_manifest(), "licence.spdxx", "CC-BY-4.0")
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SourceManifest.model_validate(data)


def test_permissions_must_come_from_the_fixed_vocabulary() -> None:
    data = with_value(accepted_manifest(), "licence.redistribution", "maybe")
    with pytest.raises(ValidationError, match="allowed"):
        SourceManifest.model_validate(data)


def test_checksum_length_depends_on_the_algorithm() -> None:
    good = {"filename": "a.zip", "record_checksum": {"algo": "md5", "value": "a" * 32}}
    SourceManifest.model_validate(
        with_value(pending_manifest(), "acquisition", {"download_files": [good]})
    )
    bad = {"filename": "a.zip", "record_checksum": {"algo": "md5", "value": "a" * 64}}
    with pytest.raises(ValidationError, match="md5 checksum is 32"):
        SourceManifest.model_validate(
            with_value(pending_manifest(), "acquisition", {"download_files": [bad]})
        )


def test_checksums_are_lowercase_hex() -> None:
    bad = {"filename": "a.zip", "record_checksum": {"algo": "md5", "value": "A" * 32}}
    with pytest.raises(ValidationError, match="lowercase hexadecimal"):
        SourceManifest.model_validate(
            with_value(pending_manifest(), "acquisition", {"download_files": [bad]})
        )


@pytest.mark.parametrize(
    "size",
    [{"min": [300, 300], "max": [200, 200]}, {"min": [0, 10], "max": [10, 10]}],
)
def test_image_size_must_be_positive_and_ordered(size: dict[str, list[int]]) -> None:
    data = with_value(pending_manifest(), "content", {"image_size_px": size})
    with pytest.raises(ValidationError, match="min <= max"):
        SourceManifest.model_validate(data)


def test_manifests_are_immutable() -> None:
    manifest = SourceManifest.model_validate(pending_manifest())
    with pytest.raises(ValidationError):
        manifest.slug = "another-slug"  # type: ignore[misc]


# --------------------------------------------------------------- public release


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("licence.redistribution", "unclear", "redistribution is unclear"),
        ("licence.redistribution", "not_allowed", "redistribution is not_allowed"),
        ("licence.derivative_work", "unclear", "derivative_work is unclear"),
    ],
)
def test_unknown_or_denied_rights_block_public_release(
    field: str, value: str, expected: str
) -> None:
    manifest = SourceManifest.model_validate(with_value(accepted_manifest(), field, value))
    assert manifest.usable_for_ingest  # still admitted for internal use
    assert not manifest.public_release_allowed
    assert expected in manifest.public_release_blockers()
