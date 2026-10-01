"""``openinspect release``: release assembly, canonical splits and packages for EVREN (M5)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from openinspect.cli.common import DataDirOption, RepoRootOption, fail, log, setup
from openinspect.dedup.config import ConfigError, load_config
from openinspect.dedup.inventory import InventoryError
from openinspect.dedup.perf import code_version
from openinspect.files import replace_bytes, sha256_bytes, sha256_file
from openinspect.ingest.layout import source_dirs
from openinspect.provenance.licences import LicenceConfigError, load_allowlist
from openinspect.provenance.records import ImageRecord
from openinspect.provenance.registry import find_repo_root
from openinspect.release.build import (
    ManifestContext,
    assemble,
    build_manifest,
    check,
    derive_splits,
    rebuild_reversed,
    write_images,
)
from openinspect.release.checks import read_image_pairs
from openinspect.release.config import (
    RELEASE_PATH,
    ReleaseConfig,
    ReleaseConfigError,
    load_release_config,
)
from openinspect.release.export import (
    FORMAT,
    ExportError,
    ExportItem,
    expected_csv,
    package_members,
    read_items,
    select_smoke,
    verify_zip,
    zip_bytes,
)
from openinspect.release.groups import read_components
from openinspect.release.manifest import (
    ANNOTATIONS,
    EXCLUDED,
    ITEMS,
    RELEASE,
    ReleaseManifest,
    annotations_table,
    excluded_table,
    items_table,
    json_bytes,
    read_manifest,
    split_csv,
    write_manifest,
    write_parquet,
)
from openinspect.release.pool import ReleaseError
from openinspect.release.report import write_report
from openinspect.release.smoke_record import (
    OBSERVED,
    SmokeRecord,
    SmokeRecordError,
    check_zip,
    load_expected,
    load_observation,
    make_record,
)
from openinspect.release.smoke_record import Generator as SmokeGenerator
from openinspect.release.smoke_record import render as render_smoke
from openinspect.release.verify import release_dir, verify_release
from openinspect.settings import DataDirError, resolve_data_dir
from openinspect.taxonomy.config import TAXONOMY_PATH, TaxonomyError, load_taxonomy
from openinspect.taxonomy.mapping import load_annotated, map_images
from openinspect.validation import QueueError, read_validation

release_app = typer.Typer(
    help="Release assembly, splits A0/A1/B, invariants and YOLO packages for EVREN.",
    no_args_is_help=True,
)

M3 = "artifacts/m3"
REPORTS = Path("reports") / "m5"
SMOKE_DIR = "evren-smoke"
M3_FILES = ("audit.json", "leakage-groups.parquet", "duplicate-pairs.parquet", "thresholds.json")


def _config(root: Path) -> ReleaseConfig:
    try:
        return load_release_config(root)
    except ReleaseConfigError as exc:
        fail(str(exc))


def primary_levels(audit_path: Path, sources: list[str]) -> dict[str, str]:
    """The chaining rule of the M3 protocol, read from the M3 audit: ``near`` if a source chains."""
    data = json.loads(audit_path.read_text(encoding="utf-8"))
    chained = next(
        (set(level["chained_sources"]) for level in data["levels"] if level["level"] == "family"),
        set(),
    )
    return {source: "near" if source in chained else "family" for source in sources}


def image_records(data: Path, slugs: list[str]) -> dict[tuple[str, str], ImageRecord]:
    records: dict[tuple[str, str], ImageRecord] = {}
    for slug in slugs:
        path = source_dirs(data, slug).records / "images.jsonl"
        for line in path.read_text(encoding="utf-8").splitlines():
            record = ImageRecord.model_validate_json(line)
            records[(slug, record.source_item_id)] = record
    return records


@release_app.command("build")
def build_command(data_dir: DataDirOption = None, repo_root: RepoRootOption = None) -> None:
    """Assemble the release: images, splits, invariants, manifest and report."""
    root, data, registry = setup(repo_root, data_dir)
    commit, dirty = code_version(root)  # the code of this process was loaded at its start
    config = _config(root)
    slugs = [lm.manifest.slug for lm in registry.loaded if lm.manifest.usable_for_ingest]
    manifests = {lm.manifest.slug: lm.manifest for lm in registry.loaded}
    try:
        taxonomy = load_taxonomy(root)
        acquisition = {s: e.acquisition_id for s, e in load_config(root).sources.items()}
        mapped = map_images(load_annotated(data, slugs, acquisition=acquisition), taxonomy)
        records = image_records(data, slugs)
        primary = primary_levels(root / M3 / "audit.json", slugs)
        components = read_components(root / M3 / "leakage-groups.parquet", primary)
        pairs = read_image_pairs(root / M3 / "duplicate-pairs.parquet")
        allowlist = load_allowlist(root / "configs" / "licences.yaml")
        validation = read_validation(root)
        assembly = assemble(mapped, taxonomy, config)
    except (
        TaxonomyError,
        ConfigError,
        InventoryError,
        OSError,
        KeyError,
        ValueError,
        LicenceConfigError,
        QueueError,
        ReleaseError,
    ) as exc:
        fail(str(exc))
    images_dir = Path("release") / config.version / "images"
    log(f"writing {len(assembly.items):,} images to <data>/{images_dir.as_posix()}")
    try:
        files = write_images(assembly.items, data / images_dir)
    except (OSError, ReleaseError) as exc:
        fail(str(exc))
    sha = [f.sha256 for f in files]
    splits = derive_splits(assembly.items, sha, components, config)
    checked = check(
        assembly.items,
        files,
        splits,
        pairs=pairs,
        primary=primary,
        records=records,
        allowlist={a.spdx for a in allowlist.allowlist},
        benchmark=set(taxonomy.benchmark_classes),
        rebuild=rebuild_reversed(assembly.items, sha, components, config),
    )
    out = release_dir(root, config.version)
    splits_dir = root / "manifests" / "splits" / config.version
    provenance = {
        key: (r.source_url, r.source_license, r.sha256_source) for key, r in records.items()
    }
    versions = {slug: m.identity.version for slug, m in manifests.items()}
    digests = {
        ITEMS: write_parquet(
            out / ITEMS,
            items_table(
                assembly.items,
                files,
                provenance,
                versions,
                components,
                splits.groups,
                splits.schemes,
                config.splits.canonical,
            ),
        ),
        ANNOTATIONS: write_parquet(out / ANNOTATIONS, annotations_table(assembly.items)),
        EXCLUDED: write_parquet(out / EXCLUDED, excluded_table(assembly.excluded)),
    }
    split_files: dict[str, tuple[str, str, str]] = {}
    for name, split in splits.schemes.items():
        csv_path = splits_dir / f"{name}__seed{config.seed}.csv"
        meta_path = csv_path.with_suffix(".meta.json")
        data_csv = split_csv(assembly.items, split)
        replace_bytes(csv_path, data_csv)
        digest = sha256_bytes(data_csv)
        replace_bytes(
            meta_path,
            json_bytes(
                {
                    "scheme": name,
                    "seed": config.seed,
                    "release": config.version,
                    "items_file": (out / ITEMS).relative_to(root).as_posix(),
                    "items_sha256": digests[ITEMS],
                    "csv_sha256": digest,
                    "code_commit": commit,
                    "measure": checked.measures[name].model_dump(mode="json"),
                }
            ),
        )
        split_files[name] = (
            csv_path.relative_to(root).as_posix(),
            digest,
            meta_path.relative_to(root).as_posix(),
        )
    inputs = {
        f"records/{slug}/{name}": sha256_file(source_dirs(data, slug).records / name)
        for slug in slugs
        for name in ("images.jsonl", "annotations.jsonl")
    }
    inputs.update({f"{M3}/{name}": sha256_file(root / M3 / name) for name in M3_FILES})
    inputs["configs/licences.yaml"] = sha256_file(root / "configs" / "licences.yaml")
    manifest = build_manifest(
        assembly,
        mapped,
        splits,
        checked,
        taxonomy=taxonomy,
        config=config,
        manifests=manifests,
        primary=primary,
        files=digests,
        split_files=split_files,
        context=ManifestContext(
            version_dir=splits_dir.relative_to(root).as_posix(),
            images_dir=images_dir.as_posix(),
            config_sha256=sha256_file(root / RELEASE_PATH),
            taxonomy_path=TAXONOMY_PATH.as_posix(),
            taxonomy_sha256=sha256_file(root / TAXONOMY_PATH),
            code_commit=commit,
            code_dirty=dirty,
            validation=validation,
            inputs=inputs,
        ),
    )
    write_manifest(out / RELEASE, manifest)
    write_report(root / REPORTS, manifest)
    typer.echo(
        f"release {manifest.version}: {manifest.counts.images:,} images, "
        f"{manifest.counts.boxes:,} boxes, "
        + ", ".join(f"{s} {n:,}" for s, n in manifest.counts.by_source.items())
    )
    for entry in manifest.splits:
        typer.echo(
            f"{entry.name}: "
            + ", ".join(f"{k} {v:,}" for k, v in entry.counts.items())
            + f"; supplied groups crossing {entry.measure.supplied_groups_crossing}"
        )
    failed = [i for i in manifest.invariants if i.status != "PASS"]
    for inv in manifest.invariants:
        typer.echo(f"{inv.id} {inv.status}: {inv.detail}")
    if failed:
        fail(f"{len(failed)} invariants failed")


@release_app.command("report")
def report_command(repo_root: RepoRootOption = None) -> None:
    """Re-render reports/m5/release.md from the committed release.json (no data needed)."""
    root = repo_root.resolve() if repo_root is not None else find_repo_root()
    config = _config(root)
    path = release_dir(root, config.version) / RELEASE
    try:
        manifest = read_manifest(path)
    except (OSError, ValidationError) as exc:
        fail(f"cannot read {RELEASE}: {exc}")
    typer.echo(f"report: {write_report(root / REPORTS, manifest).relative_to(root).as_posix()}")


@release_app.command("check")
def check_command(repo_root: RepoRootOption = None) -> None:
    """Re-check the committed release from its files: hashes and invariants (no data needed)."""
    root = repo_root.resolve() if repo_root is not None else find_repo_root()
    config = _config(root)
    manifest, problems = verify_release(root, config.version)
    for problem in problems:
        typer.echo(f"PROBLEM {problem}", err=True)
    if problems or manifest is None:
        fail(f"release {config.version}: {len(problems)} problems")
    typer.echo(
        f"release {manifest.version}: {manifest.counts.images:,} images, "
        f"{len(manifest.splits)} split schemes, invariants "
        + ", ".join(f"{i.id} {i.status}" for i in manifest.invariants)
    )


SchemeOption = Annotated[str, typer.Option("--scheme", help="Split scheme: A0, A1 or B-<source>.")]


@dataclass(frozen=True)
class Package:
    zip_rel: Path  # relative to the data directory
    members: dict[str, str]  # path in the archive -> SHA-256
    archive: bytes
    items: list[ExportItem]
    manifest: ReleaseManifest


def _package(root: Path, data: Path, config: ReleaseConfig, scheme: str, smoke: bool) -> Package:
    manifest_path = release_dir(root, config.version) / RELEASE
    try:
        manifest = read_manifest(manifest_path)
        items = read_items(release_dir(root, config.version), ITEMS, ANNOTATIONS)
    except (OSError, ValidationError) as exc:
        fail(f"cannot read the release: {exc}")
    if scheme not in {e.name for e in manifest.splits}:
        fail(f"no split scheme {scheme!r} in {RELEASE}")
    names = manifest.taxonomy.benchmark_classes
    try:
        chosen = select_smoke(items, scheme, config.smoke.counts, config.seed) if smoke else items
        kind = "EVREN import smoke test" if smoke else "full package"
        title = f"OpenInspect-Trust {config.version}, split {scheme}, {kind} (YOLO detection)"
        members = package_members(chosen, scheme, data / manifest.images_dir, names, title)
    except (OSError, ExportError) as exc:
        fail(str(exc))
    label = "evren-smoke" if smoke else scheme
    zip_rel = (
        Path("exports") / config.version / f"openinspect-trust-{config.version}-{label}-yolo.zip"
    )
    archive = zip_bytes(members)
    replace_bytes(data / zip_rel, archive)
    expected = {name: sha256_bytes(blob) for name, blob in members}
    problems = verify_zip(data / zip_rel, expected)
    if problems:
        fail("the written archive differs from its members: " + "; ".join(problems))
    return Package(zip_rel, expected, archive, list(chosen), manifest)


@release_app.command("smoke")
def smoke_command(data_dir: DataDirOption = None, repo_root: RepoRootOption = None) -> None:
    """Build the EVREN smoke-test ZIP and record the expected split of every item before upload."""
    root, data, _ = setup(repo_root, data_dir)
    config = _config(root)
    scheme = config.smoke.scheme
    package = _package(root, data, config, scheme, smoke=True)
    zip_rel, archive = package.zip_rel, package.archive
    target = release_dir(root, config.version) / SMOKE_DIR
    replace_bytes(target / "expected-splits.csv", expected_csv(package.items, scheme))
    record = {
        "package": zip_rel.name,
        "location": f"<OPENINSPECT_DATA_DIR>/{zip_rel.as_posix()}",
        "format": FORMAT,
        "scheme": scheme,
        "release": config.version,
        "release_manifest_sha256": sha256_file(release_dir(root, config.version) / RELEASE),
        "zip_sha256": sha256_bytes(archive),
        "zip_bytes": len(archive),
        "counts": dict(config.smoke.counts),
        "items": len(package.items),
        "classes": dict(enumerate(package.manifest.taxonomy.benchmark_classes)),
        "members": package.members,
        "invariant_I10": "PASS: the archive was read back and every member matches its SHA-256",
        "question": "Does EVREN keep the imported train/val/test assignment of a ZIP?",
        "how_to_verify": [
            "Import the ZIP in the EVREN UI as a VISION dataset in YOLO Detection format; keep Auto Split off.",
            "Compare the item names EVREN shows in each split with expected-splits.csv (file names are global ids).",
            "Check that the class names and ids match `classes` and that box counts per item match `boxes`.",
            "Record the result in docs/EVREN.md; change the UNKNOWN only on direct evidence.",
        ],
    }
    replace_bytes(target / "smoke.json", json_bytes(record))
    typer.echo(f"package: <data>/{zip_rel.as_posix()} ({len(archive):,} bytes)")
    typer.echo(f"sha256: {record['zip_sha256']}")
    typer.echo(f"expected splits: {(target / 'expected-splits.csv').relative_to(root).as_posix()}")


M6_ARTIFACT = Path("artifacts") / "m6" / "evren-smoke-test.json"
M6_REPORT = Path("reports") / "m6" / "evren-smoke-test.md"


@release_app.command("smoke-verify")
def smoke_verify_command(data_dir: DataDirOption = None, repo_root: RepoRootOption = None) -> None:
    """M6: compare the recorded EVREN observations with the committed expectation and the ZIP."""
    root = repo_root.resolve() if repo_root is not None else find_repo_root()
    commit, dirty = code_version(root)
    config = _config(root)
    folder = release_dir(root, config.version)
    smoke = folder / SMOKE_DIR
    try:
        observed = load_observation(smoke / OBSERVED)
        expected = load_expected(smoke, folder / ANNOTATIONS)
    except SmokeRecordError as exc:
        fail(str(exc))
    found = None
    try:
        data = resolve_data_dir(data_dir, repo_root=root)
    except DataDirError:
        log("no data directory: the ZIP itself is not re-checked")
    else:
        package = data / "exports" / config.version / expected.package
        if package.is_file():
            found = check_zip(package, expected)
        else:
            log(f"{expected.package} is not in the data directory: the ZIP is not re-checked")
    inputs = {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in (
            smoke / OBSERVED,
            smoke / "expected-splits.csv",
            smoke / "smoke.json",
            folder / ANNOTATIONS,
        )
    }
    record = make_record(
        observed,
        expected,
        found,
        inputs=inputs,
        generator=SmokeGenerator(
            command="openinspect release smoke-verify", code_commit=commit, code_dirty=dirty
        ),
    )
    blob = json_bytes(record.model_dump(mode="json"))
    replace_bytes(root / M6_ARTIFACT, blob)
    written = SmokeRecord.model_validate_json(
        blob
    )  # render what is committed, as smoke-report does
    replace_bytes(
        root / M6_REPORT, render_smoke(written, smoke.relative_to(root).as_posix()).encode("utf-8")
    )
    for c in record.checks:
        typer.echo(f"{c.result:9} {c.status:18} {c.capability}")
    typer.echo(f"M6 verdict: {record.verdict}")
    if record.verdict != "PASS":
        fail("an observation disagrees with the committed expectation")


@release_app.command("smoke-report")
def smoke_report_command(repo_root: RepoRootOption = None) -> None:
    """M6: re-render reports/m6/ from artifacts/m6/evren-smoke-test.json (no data needed)."""
    root = repo_root.resolve() if repo_root is not None else find_repo_root()
    smoke = release_dir(root, _config(root).version) / SMOKE_DIR
    try:
        record = SmokeRecord.model_validate_json((root / M6_ARTIFACT).read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        fail(f"cannot read {M6_ARTIFACT.as_posix()}: {exc}")
    replace_bytes(
        root / M6_REPORT, render_smoke(record, smoke.relative_to(root).as_posix()).encode("utf-8")
    )
    typer.echo(f"report: {M6_REPORT.as_posix()}")


@release_app.command("export")
def export_command(
    scheme: SchemeOption = "A1", data_dir: DataDirOption = None, repo_root: RepoRootOption = None
) -> None:
    """Build the full YOLO Detection ZIP of one split scheme under <data>/exports/."""
    root, data, _ = setup(repo_root, data_dir)
    config = _config(root)
    package = _package(root, data, config, scheme, smoke=False)
    zip_rel, archive = package.zip_rel, package.archive
    sidecar = (data / zip_rel).with_suffix(".json")
    replace_bytes(
        sidecar,
        json_bytes(
            {
                "package": zip_rel.name,
                "scheme": scheme,
                "zip_sha256": sha256_bytes(archive),
                "items": len(package.items),
                "members": package.members,
            }
        ),
    )
    typer.echo(
        f"package: <data>/{zip_rel.as_posix()} ({len(package.items):,} items, {len(archive):,} bytes)"
    )
    typer.echo(f"sha256: {sha256_bytes(archive)}")
