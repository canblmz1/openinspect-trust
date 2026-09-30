"""Shared pieces of the per-source adapters.

An adapter knows the real file layout of one source (seen in the archive, never guessed). If the layout
differs from what it was written for it raises :class:`AdapterError` instead of guessing.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from openinspect.ingest.imaging import ImageInfo
from openinspect.ingest.report import SEVERITY_ORDER, Anomaly, GroupingInfo, Severity
from openinspect.provenance.records import AnnotationRecord, ImageRecord, Split
from openinspect.provenance.schema import SourceManifest

Progress = Callable[[str], None]
MAX_EXAMPLES = 5


class AdapterError(Exception):
    """The archive does not look like what the adapter was written for."""


def _silent(message: str) -> None:
    return None


@dataclass(frozen=True)
class AdapterContext:
    slug: str
    manifest: SourceManifest
    root: Path  # the extracted archive
    hashes: Mapping[str, str]  # POSIX path relative to ``root`` -> SHA-256
    progress: Progress = _silent

    @property
    def source_url(self) -> str:
        url = self.manifest.identity.official_url
        if url is None:
            raise AdapterError(f"{self.slug}: the manifest has no official_url")
        return url

    @property
    def spdx(self) -> str:
        spdx = self.manifest.licence.spdx
        if spdx is None:
            raise AdapterError(f"{self.slug}: the manifest has no licence")
        return spdx

    def sha256(self, rel: str) -> str:
        try:
            return self.hashes[rel]
        except KeyError as exc:
            raise AdapterError(f"no SHA-256 for {rel}: the file list and the tree differ") from exc

    def files_in(self, rel_dir: str) -> list[str]:
        """Names of the files directly inside ``rel_dir``, sorted."""
        return sorted(p.name for p in (self.root / rel_dir).iterdir() if p.is_file())

    def require(self, *paths: str) -> None:
        missing = [p for p in paths if not (self.root / p).exists()]
        if missing:
            raise AdapterError(
                "the archive layout differs from what this adapter was written for; missing: "
                + ", ".join(missing)
            )


@dataclass
class _Accumulated:
    severity: Severity
    message: str
    count: int = 0
    examples: list[str] = field(default_factory=list)


@dataclass
class Findings:
    """What an adapter learned about a source, besides the records themselves."""

    formats_present: list[str]
    canonical_format: str
    grouping: GroupingInfo | None = None
    notes: list[str] = field(default_factory=list)
    archive_says: list[str] = field(default_factory=list)  # what the archive states about licensing
    observed: list[tuple[str, str]] = field(default_factory=list)  # extra (field, observed) facts
    _anomalies: dict[str, _Accumulated] = field(default_factory=dict)

    def anomaly(
        self,
        code: str,
        severity: Severity,
        message: str,
        example: str | None = None,
        count: int = 1,
    ) -> None:
        item = self._anomalies.setdefault(code, _Accumulated(severity, message))
        item.count += count
        if (
            example is not None
            and len(item.examples) < MAX_EXAMPLES
            and example not in item.examples
        ):
            item.examples.append(example)

    def orphans(
        self,
        kind: str,
        *,
        present_in: str,
        missing_in: str,
        names: Collection[str],
        severity: Severity = "warning",
    ) -> None:
        """Record names that exist in one place but have no counterpart in another."""
        ordered = sorted(names)
        if ordered:
            self.anomaly(
                f"orphan_{kind}_{present_in}_not_in_{missing_in}",
                severity,
                f"{kind} present in {present_in} but absent from {missing_in}",
                ordered[0],
                count=len(ordered),
            )
            for name in ordered[1:MAX_EXAMPLES]:
                self.anomaly(
                    f"orphan_{kind}_{present_in}_not_in_{missing_in}", severity, "", name, count=0
                )

    def anomalies(self) -> list[Anomaly]:
        found = [
            Anomaly(
                code=code,
                severity=a.severity,
                message=a.message,
                count=a.count,
                examples=a.examples,
            )
            for code, a in self._anomalies.items()
            if a.count > 0
        ]
        return sorted(found, key=lambda a: (SEVERITY_ORDER[a.severity], a.code))


@dataclass
class AdapterResult:
    images: list[ImageRecord]
    annotations: list[AnnotationRecord]
    findings: Findings


AdapterFn = Callable[[AdapterContext], AdapterResult]


@dataclass(frozen=True)
class AdapterSpec:
    name: str
    version: int
    run: AdapterFn


def image_record(
    ctx: AdapterContext,
    *,
    rel: str,
    info: ImageInfo,
    split: Split | None,
    labels: Sequence[str],
    annotation_source: str,
    group: str | None = None,
    subgroup: str | None = None,
    name_family: str | None = None,
    original_name: str | None = None,
    alternates: Sequence[str] = (),
    flags: Sequence[str] = (),
) -> ImageRecord:
    sha256 = ctx.sha256(rel)
    return ImageRecord(
        source_dataset=ctx.slug,
        source_item_id=rel,
        source_url=ctx.source_url,
        source_license=ctx.spdx,
        sha256=sha256,
        sha256_source=sha256,
        bytes=(ctx.root / rel).stat().st_size,
        decode_ok=info.ok,
        decode_error=info.error,
        width=info.width,
        height=info.height,
        format=info.format,
        mode=info.mode,
        exif_orientation=info.exif_orientation,
        dhash=info.dhash,
        original_split=split,
        source_group_id=group,
        source_subgroup_id=subgroup,
        name_family=name_family,
        original_name=original_name,
        original_labels=sorted(set(labels)),
        n_annotations=len(labels),
        annotation_source=annotation_source,
        alternate_paths=list(alternates),
        flags=list(flags),
    )
