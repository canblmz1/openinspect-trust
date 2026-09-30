"""The ingestion pipeline of one source, and the cross-source duplicate check.

verify archive -> extract safely (per-file SHA-256) -> adapter (images, annotations, findings)
-> records (JSONL, outside the repository) -> report (JSON, tracked) -> reconciliation with the manifest.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from openinspect.ingest.adapters import ADAPTERS
from openinspect.ingest.adapters.base import AdapterContext, AdapterError, Progress
from openinspect.ingest.download import verify_file
from openinspect.ingest.extract import ExtractedFile, ExtractError, extract_zip, format_sha256_list
from openinspect.ingest.layout import SourceDirs, source_dirs
from openinspect.ingest.report import (
    AdapterInfo,
    ArchiveCheck,
    ClassCount,
    CrossSource,
    DecodeInfo,
    DuplicateInfo,
    LicenceTrace,
    Reconciliation,
    SourceReport,
    SplitCount,
    write_json,
)
from openinspect.provenance.records import AnnotationRecord, ImageRecord
from openinspect.provenance.registry import LoadedManifest, rel_path
from openinspect.provenance.schema import SourceManifest


class IngestError(Exception):
    """A source cannot be ingested (missing or mismatching archive, unknown layout)."""


def _silent(message: str) -> None:
    return None


@dataclass(frozen=True)
class Extraction:
    files: tuple[ExtractedFile, ...]
    anomalies: tuple[str, ...]
    extracted_now: bool
    zip_crc_ok: bool


def read_sha256_list(path: Path, root: Path) -> tuple[ExtractedFile, ...]:
    files = []
    for line in path.read_text(encoding="ascii").splitlines():
        digest, _, rel = line.partition("  ")
        files.append(ExtractedFile(rel, (root / rel).stat().st_size, digest))
    return tuple(files)


def hash_tree(root: Path) -> tuple[ExtractedFile, ...]:
    files = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while block := handle.read(1 << 20):
                digest.update(block)
        files.append(
            ExtractedFile(
                path.relative_to(root).as_posix(), path.stat().st_size, digest.hexdigest()
            )
        )
    return tuple(files)


def ensure_extracted(archive: Path, dirs: SourceDirs) -> Extraction:
    """Extract ``archive`` once; later calls reuse the tree and its per-file SHA-256 list."""
    try:
        with zipfile.ZipFile(archive) as zf:
            zip_ok = zf.testzip() is None  # reads every member and checks its CRC-32
    except zipfile.BadZipFile as exc:
        raise ExtractError(f"{archive.name} is not a valid zip archive: {exc}") from exc
    list_path = dirs.records / "files.sha256"
    if not dirs.extracted.exists():
        result = extract_zip(archive, dirs.extracted)
        dirs.records.mkdir(parents=True, exist_ok=True)
        list_path.write_bytes(format_sha256_list(result.files).encode("ascii"))
        return Extraction(result.files, result.anomalies, True, zip_ok)
    if list_path.is_file():
        files = read_sha256_list(list_path, dirs.extracted)
    else:
        files = hash_tree(dirs.extracted)
        dirs.records.mkdir(parents=True, exist_ok=True)
        list_path.write_bytes(format_sha256_list(files).encode("ascii"))
    on_disk = sum(1 for p in dirs.extracted.rglob("*") if p.is_file())
    if on_disk != len(files):
        raise ExtractError(
            f"{dirs.extracted}: {on_disk} files on disk, {len(files)} in the hash list"
        )
    return Extraction(files, (), False, zip_ok)


def _write_jsonl(path: Path, records: list[ImageRecord] | list[AnnotationRecord]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = "".join(record.model_dump_json() + "\n" for record in records).encode("utf-8")
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def _duplicates(images: list[ImageRecord]) -> DuplicateInfo:
    by_hash: dict[str, list[ImageRecord]] = defaultdict(list)
    for image in images:
        by_hash[image.sha256].append(image)
    groups = [g for g in by_hash.values() if len(g) > 1]
    cross = sum(1 for g in groups if len({i.original_split for i in g if i.original_split}) > 1)
    return DuplicateInfo(
        groups=len(groups),
        redundant_files=sum(len(g) - 1 for g in groups),
        cross_split_groups=cross,
    )


def _observed_classes(annotations: list[AnnotationRecord]) -> list[ClassCount]:
    counts: Counter[str] = Counter()
    ids: dict[str, int | None] = {}
    for a in annotations:
        counts[a.original_label] += 1
        ids.setdefault(a.original_label, a.label_id)
    ordered = sorted(counts, key=lambda label: (ids[label] is None, ids[label] or 0, label))
    return [ClassCount(label=label, label_id=ids[label], count=counts[label]) for label in ordered]


def _splits(images: list[ImageRecord]) -> list[SplitCount]:
    order = {"train": 0, "val": 1, "test": 2}
    groups: dict[str, list[ImageRecord]] = defaultdict(list)
    for image in images:
        if image.original_split:
            groups[image.original_split].append(image)
    return [
        SplitCount(
            split=name,
            images=len(items),
            annotations=sum(i.n_annotations for i in items),
            images_without_annotations=sum(1 for i in items if i.n_annotations == 0),
        )
        for name, items in sorted(groups.items(), key=lambda kv: order.get(kv[0], 9))
    ]


def _reconcile(
    manifest: SourceManifest,
    images: list[ImageRecord],
    classes: list[ClassCount],
    splits: list[SplitCount],
) -> list[Reconciliation]:
    rows: list[Reconciliation] = []

    def add(field: str, value: object, observed: object) -> None:
        status: Literal["match", "mismatch", "new"] = (
            "new" if value is None else ("match" if str(value) == str(observed) else "mismatch")
        )
        rows.append(
            Reconciliation(
                field=field,
                manifest=None if value is None else str(value),
                observed=str(observed),
                status=status,
            )
        )

    content = manifest.content
    add("content.image_count", content.image_count, len(images))
    add("content.annotation_count", content.annotation_count, sum(c.count for c in classes))
    observed = {c.label: c.count for c in classes}
    listed = {c.label for c in content.original_classes}
    for entry in content.original_classes:
        add(
            f"content.original_classes[{entry.label}].count",
            entry.count,
            observed.get(entry.label, 0),
        )
    for label in sorted(set(observed) - listed):
        rows.append(
            Reconciliation(
                field=f"content.original_classes[{label}]",
                manifest=None,
                observed=str(observed[label]),
                status="new",
            )
        )
    if content.official_splits:
        by_split = {s.split: s for s in splits}
        for key, value in content.official_splits.counts.items():
            split, _, kind = key.partition("_")
            if kind == "":
                split, kind = key, "images"
            found = by_split.get(split)
            seen = (
                None if found is None else (found.annotations if kind == "boxes" else found.images)
            )
            add(f"content.official_splits.counts.{key}", value, 0 if seen is None else seen)
    size = content.image_size_px
    decoded = [(i.width, i.height) for i in images if i.width and i.height]
    if size and decoded:
        add(
            "content.image_size_px.min",
            size.min,
            [min(w for w, _ in decoded), min(h for _, h in decoded)],
        )
        add(
            "content.image_size_px.max",
            size.max,
            [max(w for w, _ in decoded), max(h for _, h in decoded)],
        )
    return rows


def run_source(
    item: LoadedManifest,
    *,
    repo_root: Path,
    data_dir: Path,
    progress: Progress = _silent,
) -> SourceReport:
    manifest = item.manifest
    slug = manifest.slug
    if not manifest.usable_for_ingest:
        raise IngestError(f"{slug}: only accepted sources may be ingested")
    spec = ADAPTERS.get(slug)
    if spec is None:
        raise IngestError(f"{slug}: no adapter has been written for this source")
    specs = manifest.acquisition.download_files
    if len(specs) != 1:
        raise IngestError(
            f"{slug}: expected exactly one archive in the manifest, found {len(specs)}"
        )
    dirs = source_dirs(data_dir, slug)
    archive = dirs.raw / specs[0].filename
    if not archive.is_file():
        raise IngestError(
            f"{slug}: {archive.name} is not downloaded; run `openinspect ingest download {slug}`"
        )
    verification, digests, size = verify_file(archive, specs[0])
    if not verification.passed:
        raise IngestError(
            f"{slug}: {archive.name} does not match the repository record: {verification.describe()}"
        )
    recorded = (manifest.acquisition.archive_sha256 or {}).get(specs[0].filename)
    if recorded is not None and recorded != digests["sha256"]:
        raise IngestError(
            f"{slug}: the archive SHA-256 differs from the one recorded in the manifest"
        )
    try:
        extraction = ensure_extracted(archive, dirs)
    except ExtractError as exc:
        raise IngestError(f"{slug}: {exc}") from exc
    ctx = AdapterContext(
        slug=slug,
        manifest=manifest,
        root=dirs.extracted,
        hashes={f.path: f.sha256 for f in extraction.files},
        progress=progress,
    )
    try:
        result = spec.run(ctx)
    except AdapterError as exc:
        raise IngestError(f"{slug}: {exc}") from exc
    images = sorted(result.images, key=lambda i: i.source_item_id)
    annotations = sorted(result.annotations, key=lambda a: (a.source_item_id, a.ann_index))
    findings = result.findings
    for anomaly in extraction.anomalies:
        findings.anomaly(
            "archive_member_anomaly",
            "warning",
            "an archive member needed special handling",
            anomaly,
        )
    failed = [i.source_item_id for i in images if not i.decode_ok]
    classes = _observed_classes(annotations)
    splits = _splits(images)
    digests_out = {
        "images_jsonl": _write_jsonl(dirs.records / "images.jsonl", images),
        "annotations_jsonl": _write_jsonl(dirs.records / "annotations.jsonl", annotations),
        "files_list": hashlib.sha256((dirs.records / "files.sha256").read_bytes()).hexdigest()
        if (dirs.records / "files.sha256").is_file()
        else hashlib.sha256(format_sha256_list(extraction.files).encode("ascii")).hexdigest(),
    }
    anomalies = findings.anomalies()
    if findings.grouping is None:
        raise IngestError(f"{slug}: the adapter produced no grouping analysis")
    archived = manifest.archived_evidence_paths()
    report = SourceReport(
        slug=slug,
        dataset_name=manifest.dataset_name,
        archive=ArchiveCheck(
            filename=archive.name,
            bytes=size,
            size_ok=verification.size_ok,
            checksum_algo=verification.algo,
            checksum_ok=verification.checksum_ok,
            sha256=digests["sha256"],
            files_extracted=len(extraction.files),
            zip_crc_ok=extraction.zip_crc_ok,
        ),
        adapter=AdapterInfo(
            name=spec.name,
            version=spec.version,
            status="ok_with_warnings" if any(a.severity != "info" for a in anomalies) else "ok",
            canonical_format=findings.canonical_format,
            formats_present=findings.formats_present,
        ),
        images=len(images),
        annotations=len(annotations),
        decode=DecodeInfo(
            images=len(images),
            decodable=len(images) - len(failed),
            failed=len(failed),
            failures=failed[:5],
        ),
        classes=classes,
        splits=splits,
        grouping=findings.grouping,
        exact_duplicates=_duplicates(images),
        anomalies=anomalies,
        reconciliation=_reconcile(manifest, images, classes, splits),
        licence=LicenceTrace(
            manifest=rel_path(item.path, repo_root),
            spdx=manifest.licence.spdx,
            licence_url=manifest.licence.licence_url,
            attribution_in_manifest=bool(manifest.licence.attribution_text),
            evidence_files=len(archived),
            archive_says=findings.archive_says,
        ),
        digests=digests_out,
        notes=findings.notes,
    )
    write_json(repo_root / "manifests" / "ingest" / slug / "report.json", report)
    return report


def compute_cross_source(data_dir: Path, slugs: list[str]) -> CrossSource:
    """Images whose bytes (SHA-256) occur in two different sources."""
    owners: dict[str, list[str]] = defaultdict(list)
    per_source: dict[str, int] = {}
    for slug in slugs:
        path = source_dirs(data_dir, slug).records / "images.jsonl"
        count = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            owners[record["sha256"]].append(f"{slug}:{record['source_item_id']}")
            count += 1
        per_source[slug] = count
    shared = [items for items in owners.values() if len({i.split(":", 1)[0] for i in items}) > 1]
    return CrossSource(
        sources=sorted(slugs),
        images_per_source=dict(sorted(per_source.items())),
        shared_sha256=len(shared),
        groups=sorted(sorted(g) for g in shared)[:20],
    )
