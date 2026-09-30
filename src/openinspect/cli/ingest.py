"""``openinspect ingest download | extract | inspect | run | report``."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import httpx
import typer

from openinspect.cli.common import (
    AllOption,
    DataDirOption,
    RepoRootOption,
    SlugsArgument,
)
from openinspect.cli.common import fail as _fail
from openinspect.cli.common import log as _log
from openinspect.cli.common import select_sources as _select
from openinspect.cli.common import setup as _setup
from openinspect.ingest.download import DownloadError, DownloadRecord, download
from openinspect.ingest.extract import ExtractError
from openinspect.ingest.inventory import summarize_tree
from openinspect.ingest.layout import source_dirs
from openinspect.ingest.manifest_patch import ManifestPatchError, set_acquisition_fields
from openinspect.ingest.pipeline import (
    IngestError,
    compute_cross_source,
    ensure_extracted,
    run_source,
)
from openinspect.ingest.report import SourceReport, render_markdown, write_json
from openinspect.provenance.registry import LoadedManifest, Registry
from openinspect.settings import DataDirError, ensure_free_space

ingest_app = typer.Typer(
    help="Download, verify, unpack, inspect and ingest the archives of accepted sources.",
    no_args_is_help=True,
)


def _http_client() -> httpx.Client | None:
    """Hook for tests: return a client with a mock transport. ``None`` means the default client."""
    return None


def _ingest_dir(root: Path, slug: str) -> Path:
    return root / "manifests" / "ingest" / slug


# --------------------------------------------------------------------------------- download


@ingest_app.command("download")
def download_command(
    slugs: SlugsArgument = None,
    all_sources: AllOption = False,
    data_dir: DataDirOption = None,
    repo_root: RepoRootOption = None,
) -> None:
    """Download the archives of accepted sources and verify them against the repository record."""
    root, data, registry = _setup(repo_root, data_dir)
    selected = _select(registry, slugs, all_sources)
    needed = sum(f.bytes or 0 for lm in selected for f in lm.manifest.acquisition.download_files)
    try:
        ensure_free_space(data, needed * 3)  # archive + extracted copy + margin
    except DataDirError as exc:
        _fail(str(exc))
    for item in selected:
        manifest = item.manifest
        dirs = source_dirs(data, manifest.slug)
        records: list[DownloadRecord] = []
        for spec in manifest.acquisition.download_files:
            last_reported = -1

            def progress(done: int, total: int | None, name: str = spec.filename) -> None:
                nonlocal last_reported
                step = int(done / (total or done or 1) * 10)
                if step > last_reported:
                    last_reported = step
                    of = f" of {total / 1e6:.1f} MB" if total else ""
                    _log(f"  {name}: {done / 1e6:.1f} MB{of}")

            typer.echo(f"{manifest.slug}: {spec.filename}")
            try:
                record = download(spec, dirs.raw, client=_http_client(), progress=progress)
            except DownloadError as exc:
                _fail(str(exc))
            records.append(record)
            state = "already present, verified" if record.skipped else "downloaded, verified"
            typer.echo(
                f"  {state}: {record.bytes} bytes, sha256 {record.sha256[:16]}..., "
                f"{record.checksum_algo or 'no'} checksum "
                f"{'matches' if record.checksum_ok else 'n/a'}"
            )
        _write_download_record(root, manifest.slug, records)
        archive_hashes = {r.filename: r.sha256 for r in records}
        first_download = manifest.acquisition.download_date is None
        try:
            set_acquisition_fields(
                item.path,
                download_date=datetime.now(UTC).date() if first_download else None,
                archive_sha256=archive_hashes,
            )
        except ManifestPatchError as exc:
            _fail(f"{manifest.slug}: {exc}")


def _write_download_record(root: Path, slug: str, records: list[DownloadRecord]) -> None:
    path = _ingest_dir(root, slug) / "download.json"
    if path.is_file() and all(r.skipped for r in records):
        return  # nothing new happened: keep the original record (and its timestamps)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"slug": slug, "files": [r.as_dict() for r in records]}
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    path.write_bytes(text.encode("utf-8"))  # LF on every platform, like the other reports


# ---------------------------------------------------------------------------------- extract


def _archive_of(item: LoadedManifest, data: Path) -> Path:
    specs = item.manifest.acquisition.download_files
    if len(specs) != 1:
        _fail(f"{item.manifest.slug}: expected exactly one archive, found {len(specs)}")
    archive = source_dirs(data, item.manifest.slug).raw / specs[0].filename
    if not archive.is_file():
        _fail(f"{item.manifest.slug}: not downloaded yet: {archive.name}")
    return archive


@ingest_app.command("extract")
def extract_command(
    slugs: SlugsArgument = None,
    all_sources: AllOption = False,
    data_dir: DataDirOption = None,
    repo_root: RepoRootOption = None,
) -> None:
    """Unpack the downloaded archives safely and write a SHA-256 for every extracted file."""
    _, data, registry = _setup(repo_root, data_dir)
    for item in _select(registry, slugs, all_sources):
        slug = item.manifest.slug
        try:
            outcome = ensure_extracted(_archive_of(item, data), source_dirs(data, slug))
        except ExtractError as exc:
            _fail(f"{slug}: {exc}")
        state = "extracted" if outcome.extracted_now else "already extracted"
        typer.echo(
            f"{slug}: {state}, {len(outcome.files)} files, "
            f"{sum(f.size for f in outcome.files)} bytes, "
            f"zip CRC-32 {'ok' if outcome.zip_crc_ok else 'FAILED'}, "
            f"{len(outcome.anomalies)} anomalies"
        )
        for anomaly in outcome.anomalies:
            typer.echo(f"  anomaly: {anomaly}")


# ---------------------------------------------------------------------------------- inspect


@ingest_app.command("inspect")
def inspect_command(
    slug: Annotated[str, typer.Argument(help="Source id.")],
    depth: Annotated[int, typer.Option("--depth", min=0, help="Directory levels to show.")] = 3,
    data_dir: DataDirOption = None,
    repo_root: RepoRootOption = None,
) -> None:
    """Show the layout of an extracted source: directories, file counts per extension, examples."""
    _, data, registry = _setup(repo_root, data_dir)
    if registry.get(slug) is None:
        _fail(f"no source with slug {slug!r}")
    extracted = source_dirs(data, slug).extracted
    if not extracted.is_dir():
        _fail(f"{slug}: not extracted yet")
    typer.echo(summarize_tree(extracted, depth=depth))


# --------------------------------------------------------------------------- run and report


def _load_reports(root: Path, slugs: Sequence[str]) -> list[SourceReport]:
    found = []
    for slug in slugs:
        path = _ingest_dir(root, slug) / "report.json"
        if path.is_file():
            found.append(SourceReport.model_validate_json(path.read_text(encoding="utf-8")))
    return found


def _write_reports(root: Path, data: Path, registry: Registry) -> Path:
    slugs = [lm.manifest.slug for lm in registry.loaded if lm.manifest.usable_for_ingest]
    reports = _load_reports(root, slugs)
    if not reports:
        _fail("no ingest report found: run `openinspect ingest run --all` first")
    with_records = [
        r.slug for r in reports if (source_dirs(data, r.slug).records / "images.jsonl").is_file()
    ]
    cross = compute_cross_source(data, with_records) if len(with_records) > 1 else None
    if cross is not None:
        write_json(root / "manifests" / "ingest" / "cross_source.json", cross)
    target = root / "reports" / "m2-ingest-report.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(render_markdown(reports, cross).encode("utf-8"))
    return target


@ingest_app.command("run")
def run_command(
    slugs: SlugsArgument = None,
    all_sources: AllOption = False,
    data_dir: DataDirOption = None,
    repo_root: RepoRootOption = None,
) -> None:
    """Verify, extract and ingest accepted sources, then write the ingest report."""
    root, data, registry = _setup(repo_root, data_dir)
    selected = _select(registry, slugs, all_sources)
    for item in selected:
        slug = item.manifest.slug
        typer.echo(f"{slug}: ingesting")
        try:
            report = run_source(item, repo_root=root, data_dir=data, progress=_log)
        except IngestError as exc:
            _fail(str(exc))
        typer.echo(
            f"  {report.images:,} images ({report.decode.failed} undecodable), "
            f"{report.annotations:,} annotations, adapter {report.adapter.status}, "
            f"{len(report.anomalies)} anomaly kinds"
        )
        try:
            set_acquisition_fields(
                item.path, sha256_manifest=f"manifests/ingest/{slug}/report.json"
            )
        except ManifestPatchError as exc:
            _fail(f"{slug}: {exc}")
    target = _write_reports(root, data, registry)
    typer.echo(f"report: {target.relative_to(root).as_posix()}")


@ingest_app.command("report")
def report_command(
    data_dir: DataDirOption = None,
    repo_root: RepoRootOption = None,
) -> None:
    """Rebuild reports/m2-ingest-report.md from the stored per-source reports."""
    root, data, registry = _setup(repo_root, data_dir)
    target = _write_reports(root, data, registry)
    typer.echo(f"report: {target.relative_to(root).as_posix()}")
