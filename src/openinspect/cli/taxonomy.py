"""``openinspect taxonomy``: the normalized taxonomy and the label-quality audit (M4)."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from openinspect.cli.common import (
    AllOption,
    DataDirOption,
    RepoRootOption,
    SlugsArgument,
    fail,
    log,
    select_sources,
    setup,
)
from openinspect.dedup.config import ConfigError, load_config
from openinspect.dedup.inventory import InventoryError
from openinspect.dedup.perf import code_version
from openinspect.dedup.thresholds import Thresholds
from openinspect.files import sha256_file
from openinspect.ingest.layout import source_dirs
from openinspect.ingest.report import SourceReport
from openinspect.provenance.registry import Registry, find_repo_root, load_registry
from openinspect.taxonomy.audit import M4Run, build_audit
from openinspect.taxonomy.config import (
    TAXONOMY_PATH,
    Taxonomy,
    TaxonomyError,
    check_against_sources,
    load_taxonomy,
)
from openinspect.taxonomy.mapping import load_annotated, map_images, used_labels
from openinspect.taxonomy.quality import all_findings, read_pairs
from openinspect.taxonomy.report import write_reports
from openinspect.taxonomy.tables import AUDIT, read_audit, write_artifacts, write_audit
from openinspect.validation import QueueError, read_validation

taxonomy_app = typer.Typer(
    help="Normalized taxonomy and label-quality audit: original labels are never changed.",
    no_args_is_help=True,
)

ARTIFACTS = Path("artifacts") / "m4"
REPORTS = Path("reports") / "m4"
M3_ARTIFACTS = Path("artifacts") / "m3"
M3_PAIRS = "duplicate-pairs.parquet"
M3_THRESHOLDS = "thresholds.json"

OutOption = Annotated[
    Path | None, typer.Option("--out", file_okay=False, help="Artifact folder (artifacts/m4).")
]
ReportsOption = Annotated[
    Path | None, typer.Option("--reports", file_okay=False, help="Report folder (reports/m4).")
]
M3Option = Annotated[
    Path | None,
    typer.Option("--m3", file_okay=False, help="M3 artifact folder with the similarity pairs."),
]


def declared(registry: Registry, slugs: list[str]) -> dict[str, list[str]]:
    """The class labels each source manifest declares."""
    out: dict[str, list[str]] = {}
    for slug in slugs:
        item = registry.get(slug)
        if item is not None:
            out[slug] = [c.label for c in item.manifest.content.original_classes]
    return out


def used_by_ingest(root: Path, slugs: list[str]) -> dict[str, list[str]]:
    """The labels the committed ingest reports count at least once (no data directory needed)."""
    out: dict[str, list[str]] = {}
    for slug in slugs:
        path = root / "manifests" / "ingest" / slug / "report.json"
        try:
            report = SourceReport.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as exc:
            fail(f"{slug}: cannot read its ingest report: {exc}")
        out[slug] = sorted(c.label for c in report.classes if c.count > 0)
    return out


def _taxonomy(root: Path) -> Taxonomy:
    try:
        return load_taxonomy(root)
    except TaxonomyError as exc:
        fail(str(exc))


def _report_problems(problems: list[str]) -> None:
    for problem in problems:
        typer.echo(f"PROBLEM {problem}", err=True)
    if problems:
        fail(f"{len(problems)} problems with {TAXONOMY_PATH.as_posix()}")


@taxonomy_app.command("check")
def check_command(repo_root: RepoRootOption = None) -> None:
    """Check the taxonomy against the source manifests and the ingest reports (no data needed)."""
    root = repo_root.resolve() if repo_root is not None else find_repo_root()
    registry = load_registry(root)
    taxonomy = _taxonomy(root)
    slugs = [lm.manifest.slug for lm in registry.loaded if lm.manifest.usable_for_ingest]
    _report_problems(
        check_against_sources(taxonomy, declared(registry, slugs), used_by_ingest(root, slugs))
    )
    statuses = Counter(m.status for labels in taxonomy.mappings.values() for m in labels.values())
    typer.echo(
        f"taxonomy: {len(taxonomy.classes)} normalized classes, "
        + ", ".join(f"{status} {n}" for status, n in sorted(statuses.items()))
    )
    typer.echo("benchmark classes: " + ", ".join(taxonomy.benchmark_classes))


@taxonomy_app.command("audit")
def audit_command(
    slugs: SlugsArgument = None,
    all_sources: AllOption = False,
    out: OutOption = None,
    reports: ReportsOption = None,
    m3: M3Option = None,
    data_dir: DataDirOption = None,
    repo_root: RepoRootOption = None,
) -> None:
    """Map every box, run the label-quality checks, write artifacts/m4 and reports/m4."""
    root, data, registry = setup(repo_root, data_dir)
    commit, dirty = code_version(root)  # the code of this process was loaded at its start
    chosen = [lm.manifest.slug for lm in select_sources(registry, slugs, all_sources)]
    taxonomy = _taxonomy(root)
    m3_dir = m3 or root / M3_ARTIFACTS
    try:
        config = load_config(root)
        acquisition = {slug: entry.acquisition_id for slug, entry in config.sources.items()}
        annotated = load_annotated(data, chosen, acquisition=acquisition)
        thresholds = Thresholds.model_validate_json(
            (m3_dir / M3_THRESHOLDS).read_text(encoding="utf-8")
        )
        pairs = read_pairs(m3_dir / M3_PAIRS)
        validation = read_validation(root)
    except (ConfigError, InventoryError, OSError, ValidationError, QueueError) as exc:
        fail(str(exc))
    labels = declared(registry, chosen)
    _report_problems(check_against_sources(taxonomy, labels, used_labels(annotated)))
    try:
        mapped = map_images(annotated, taxonomy)
    except TaxonomyError as exc:
        fail(str(exc))
    findings, agreement = all_findings(mapped, taxonomy, pairs, thresholds.phash_candidate)
    target = out or root / ARTIFACTS
    digests = write_artifacts(target, mapped, taxonomy, findings)
    inputs = {
        f"records/{slug}/{name}": sha256_file(source_dirs(data, slug).records / name)
        for slug in chosen
        for name in ("images.jsonl", "annotations.jsonl")
    }
    for name in (M3_PAIRS, M3_THRESHOLDS):
        inputs[f"{M3_ARTIFACTS.as_posix()}/{name}"] = sha256_file(m3_dir / name)
    run = M4Run(
        code_commit=commit,
        code_dirty=dirty,
        taxonomy_sha256=sha256_file(root / TAXONOMY_PATH),
        phash_max=thresholds.phash_candidate,
        near_threshold=thresholds.near,
    )
    audit = build_audit(
        mapped, taxonomy, labels, findings, agreement, run=run, inputs=inputs, validation=validation
    ).model_copy(update={"artifacts": digests})
    write_audit(target / AUDIT, audit)
    written = write_reports(reports or root / REPORTS, audit, taxonomy)
    for s in audit.sources:
        typer.echo(
            f"{s.source}: {s.images:,} images, {s.eligible_images:,} eligible, "
            f"{s.excluded_images:,} excluded, {s.negatives:,} negatives"
        )
    typer.echo("benchmark classes: " + ", ".join(audit.benchmark_classes))
    typer.echo(f"review-required rows: {audit.review_rows:,}")
    log(f"reports: {len(written)} files")


@taxonomy_app.command("report")
def report_command(
    out: OutOption = None, reports: ReportsOption = None, repo_root: RepoRootOption = None
) -> None:
    """Re-render reports/m4 from artifacts/m4/audit.json and the taxonomy (no data needed)."""
    root = repo_root.resolve() if repo_root is not None else find_repo_root()
    source = (out or root / ARTIFACTS) / AUDIT
    try:
        audit = read_audit(source)
    except (OSError, ValidationError) as exc:
        fail(f"cannot read {source.name}: {exc}")
    taxonomy = _taxonomy(root)
    if sha256_file(root / TAXONOMY_PATH) != audit.run.taxonomy_sha256:
        fail(
            f"{TAXONOMY_PATH.as_posix()} changed since the audit; run `openinspect taxonomy audit`"
        )
    written = write_reports(reports or root / REPORTS, audit, taxonomy)
    typer.echo(f"reports: {len(written)} files")
