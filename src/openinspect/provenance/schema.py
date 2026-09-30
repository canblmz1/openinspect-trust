"""Schema of a source manifest (``manifests/sources/<slug>.yaml``).

The schema checks shape and internal consistency: value formats, enumerations, unknown keys and
the status rules that depend only on the manifest itself. Rules that need outside data (the licence
allowlist, evidence files on disk) live in :mod:`openinspect.provenance.validate`.

Two tiers of acceptance (decision T4):

* ``accepted``: admitted for download and internal research use.
* public release: additionally needs ``redistribution`` and ``derivative_work`` to be ``allowed``;
  see :meth:`SourceManifest.public_release_blockers`.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = 1

SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")
SPDX_RE = re.compile(r"(?:LicenseRef-[A-Za-z0-9.-]+|[A-Za-z0-9][A-Za-z0-9.+-]*)")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
URL_RE = re.compile(r"https?://[^\s/?#]+[^\s]*", re.IGNORECASE)
DRIVE_RE = re.compile(r"[A-Za-z]:")
HEX_LENGTH = {"md5": 32, "sha1": 40, "sha256": 64, "sha512": 128}

Status = Literal["pending", "accepted", "rejected"]
Permission = Literal["allowed", "not_allowed", "unclear"]


def _check_slug(value: str) -> str:
    if not 3 <= len(value) <= 48 or not SLUG_RE.fullmatch(value):
        raise ValueError(
            f"invalid slug {value!r}: use 3-48 characters, lowercase letters, digits and "
            "single hyphens"
        )
    return value


def _check_doi(value: str) -> str:
    if not DOI_RE.fullmatch(value):
        raise ValueError(
            f"invalid DOI {value!r}: give the bare DOI (for example 10.5281/zenodo.123), "
            "not a URL and not a 'doi:' prefix"
        )
    return value


def _check_url(value: str) -> str:
    if not URL_RE.fullmatch(value):
        raise ValueError(f"invalid URL {value!r}: it must start with http:// or https://")
    return value


def _check_spdx(value: str) -> str:
    if not SPDX_RE.fullmatch(value):
        raise ValueError(f"invalid SPDX licence id {value!r}")
    return value


def _check_sha256(value: str) -> str:
    if not SHA256_RE.fullmatch(value):
        raise ValueError("a SHA-256 is 64 lowercase hexadecimal characters")
    return value


def _check_repo_path(value: str) -> str:
    parts = value.split("/")
    if (
        not value
        or "\\" in value
        or value.startswith("/")
        or DRIVE_RE.match(value)
        or ".." in parts
    ):
        raise ValueError(
            f"invalid repository path {value!r}: use a relative POSIX path without '..'"
        )
    return value


Slug = Annotated[str, AfterValidator(_check_slug)]
Doi = Annotated[str, AfterValidator(_check_doi)]
Url = Annotated[str, AfterValidator(_check_url)]
Spdx = Annotated[str, AfterValidator(_check_spdx)]
Sha256 = Annotated[str, AfterValidator(_check_sha256)]
RepoPath = Annotated[str, AfterValidator(_check_repo_path)]


class StrictModel(BaseModel):
    """Base for every schema model: unknown keys are errors, instances are immutable."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Decision(StrictModel):
    status: Status | None = None
    decided_by: str | None = None
    decided_on: date | None = None
    evidence: list[RepoPath] = Field(default_factory=list)
    reason: str | None = None


class Identity(StrictModel):
    official_url: Url | None = None
    doi: Doi | None = None
    paper_doi: Doi | None = None
    paper_url: Url | None = None
    code_repository: Url | None = None
    creators: list[str] = Field(default_factory=list)
    publisher_repository: str | None = None
    is_original_upload: bool | None = None
    version: str | None = None
    published_on: date | None = None


class StatedIn(StrictModel):
    where: Literal["repository_record", "doi_registry", "readme", "paper", "licence_file"]
    value: str = Field(min_length=1)


class Evidence(StrictModel):
    kind: str = Field(min_length=1)
    url: Url
    retrieved_on: date
    archived_path: RepoPath | None = None
    sha256: Sha256 | None = None

    @model_validator(mode="after")
    def _path_and_hash_go_together(self) -> Self:
        if (self.archived_path is None) != (self.sha256 is None):
            raise ValueError("archived_path and sha256 must be set together")
        return self


class Licence(StrictModel):
    spdx: Spdx | None = None
    licence_url: Url | None = None
    stated_in: list[StatedIn] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    redistribution: Permission | None = None
    derivative_work: Permission | None = None
    commercial_use: Permission | None = None
    attribution_required: bool | None = None
    attribution_text: str | None = None
    changes_must_be_indicated: bool | None = None
    verified_on: date | None = None
    evidence: list[Evidence] = Field(default_factory=list)


class Checksum(StrictModel):
    algo: Literal["md5", "sha1", "sha256", "sha512"]
    value: str

    @model_validator(mode="after")
    def _hex_of_the_right_length(self) -> Self:
        expected = HEX_LENGTH[self.algo]
        if not re.fullmatch(rf"[0-9a-f]{{{expected}}}", self.value):
            raise ValueError(
                f"a {self.algo} checksum is {expected} lowercase hexadecimal characters"
            )
        return self


class DownloadFile(StrictModel):
    url: Url | None = None
    filename: str = Field(min_length=1)
    bytes: int | None = Field(default=None, ge=0)
    record_checksum: Checksum | None = None


class Acquisition(StrictModel):
    download_method: Literal["http", "api", "git"] | None = None
    download_files: list[DownloadFile] = Field(default_factory=list)
    download_date: date | None = None
    archive_sha256: dict[str, Sha256] | None = None
    sha256_manifest: RepoPath | None = None


class ClassInfo(StrictModel):
    label: str = Field(min_length=1)
    meaning: str | None = None
    count: int | None = Field(default=None, ge=0)


class ImageSize(StrictModel):
    min: Annotated[list[int], Field(min_length=2, max_length=2)]
    max: Annotated[list[int], Field(min_length=2, max_length=2)]

    @model_validator(mode="after")
    def _positive_and_ordered(self) -> Self:
        if any(v <= 0 for v in (*self.min, *self.max)) or any(
            low > high for low, high in zip(self.min, self.max, strict=True)
        ):
            raise ValueError("image_size_px needs positive sizes with min <= max")
        return self


class OfficialSplits(StrictModel):
    scheme: str = Field(min_length=1)
    counts: dict[str, Annotated[int, Field(ge=0)]]
    how_made: str | None = None


class Content(StrictModel):
    domain: str | None = None
    task: Literal["detection", "segmentation", "classification"] | None = None
    annotation_format: list[str] = Field(default_factory=list)
    annotation_tool: str | None = None
    image_count: int | None = Field(default=None, ge=0)
    annotation_count: int | None = Field(default=None, ge=0)
    image_size_px: ImageSize | None = None
    pixel_pitch_um: float | None = Field(default=None, gt=0)
    colour: Literal["rgb", "grayscale"] | None = None
    original_classes: list[ClassInfo] = Field(default_factory=list)
    official_splits: OfficialSplits | None = None
    source_group_key: str | None = None


class ProvenanceRisks(StrictModel):
    acquisition_environment: str | None = None
    independence_notes: str | None = None
    known_duplicates: str | None = None
    known_weaknesses: list[str] = Field(default_factory=list)
    synthetic_or_engineered_defects: bool | Literal["partial"] | None = None


class Citation(StrictModel):
    citation_text: str | None = None
    bibtex: str | None = None


class SourceManifest(StrictModel):
    """One dataset source: identity, licence, evidence, content and the decision taken on it."""

    schema_version: Literal[1]
    slug: Slug
    dataset_name: str = Field(min_length=1)
    status: Status
    decision: Decision = Field(default_factory=Decision)
    identity: Identity = Field(default_factory=Identity)
    licence: Licence = Field(default_factory=Licence)
    acquisition: Acquisition = Field(default_factory=Acquisition)
    content: Content = Field(default_factory=Content)
    provenance_risks: ProvenanceRisks = Field(default_factory=ProvenanceRisks)
    citation: Citation = Field(default_factory=Citation)
    notes: str | None = None

    @model_validator(mode="after")
    def _status_rules(self) -> Self:
        problems = self.status_problems()
        if problems:
            raise ValueError(f"status {self.status!r} is not justified: " + "; ".join(problems))
        return self

    def archived_evidence_paths(self) -> set[str]:
        """Repository-relative paths of the licence evidence that has been archived."""
        return {e.archived_path for e in self.licence.evidence if e.archived_path}

    def status_problems(self) -> list[str]:
        """Problems that contradict the claimed ``status`` (empty means consistent)."""
        if self.status == "pending":
            if self.decision.status not in (None, "pending"):
                return [
                    f"decision.status is {self.decision.status!r} but the source is still pending"
                ]
            return []
        problems = self._decision_problems()
        if self.status == "accepted":
            problems += self._acceptance_problems()
        return problems

    def _decision_problems(self) -> list[str]:
        dec = self.decision
        problems: list[str] = []
        if dec.status != self.status:
            problems.append(f"decision.status must be {self.status!r}")
        if not dec.decided_by:
            problems.append("decision.decided_by is missing")
        if dec.decided_on is None:
            problems.append("decision.decided_on is missing")
        if not dec.reason:
            problems.append("decision.reason is missing")
        archived = self.archived_evidence_paths()
        if self.status == "accepted" and not dec.evidence:
            problems.append("decision.evidence is empty")
        unknown = sorted(set(dec.evidence) - archived)
        if unknown:
            problems.append(
                f"decision.evidence is not archived licence evidence: {', '.join(unknown)}"
            )
        return problems

    def _acceptance_problems(self) -> list[str]:
        ident, lic = self.identity, self.licence
        problems: list[str] = []
        if not ident.official_url:
            problems.append("identity.official_url is missing")
        if not ident.creators:
            problems.append("identity.creators is empty")
        if not ident.version:
            problems.append("identity.version is missing")
        if ident.is_original_upload is not True:
            problems.append("identity.is_original_upload must be true (no mirrors or re-uploads)")
        if not lic.spdx:
            problems.append("licence.spdx is missing")
        if not lic.licence_url:
            problems.append("licence.licence_url is missing")
        for name in ("redistribution", "derivative_work", "commercial_use"):
            if getattr(lic, name) is None:
                problems.append(f"licence.{name} is unanswered")
        if lic.attribution_required is None:
            problems.append("licence.attribution_required is unanswered")
        elif lic.attribution_required and not lic.attribution_text:
            problems.append("licence.attribution_text is missing although attribution is required")
        if lic.changes_must_be_indicated is None:
            problems.append("licence.changes_must_be_indicated is unanswered")
        if lic.verified_on is None:
            problems.append("licence.verified_on is missing")
        if not self.archived_evidence_paths():
            problems.append("licence.evidence has no archived entry (archived_path and sha256)")
        return problems

    @property
    def usable_for_ingest(self) -> bool:
        """Only accepted sources may be downloaded and ingested."""
        return self.status == "accepted"

    def public_release_blockers(self) -> list[str]:
        """Reasons this source cannot be part of a public release (empty = releasable)."""
        if self.status != "accepted":
            return [f"status is {self.status}, not accepted"]
        lic = self.licence
        blockers: list[str] = []
        if lic.redistribution != "allowed":
            blockers.append(f"redistribution is {lic.redistribution or 'unanswered'}")
        if lic.derivative_work != "allowed":
            blockers.append(f"derivative_work is {lic.derivative_work or 'unanswered'}")
        return blockers

    @property
    def public_release_allowed(self) -> bool:
        return not self.public_release_blockers()
