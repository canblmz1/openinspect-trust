"""``openinspect source add | list | show | validate``."""

from __future__ import annotations

import json
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer
from pydantic import ValidationError

from openinspect.provenance.licences import LicenceAllowlist, LicenceConfigError, load_allowlist
from openinspect.provenance.registry import (
    DuplicateSourceError,
    Issue,
    LoadedManifest,
    add_manifest,
    find_repo_root,
    load_registry,
    manifests_dir_for,
    parse_manifest_text,
    rel_path,
    schema_issues,
)
from openinspect.provenance.schema import SourceManifest
from openinspect.provenance.validate import validate_manifest, validate_registry, verify_evidence

source_app = typer.Typer(
    help="Registry of dataset sources (manifests/sources/*.yaml).", no_args_is_help=True
)

LICENCES_PATH = Path("configs") / "licences.yaml"


class StatusChoice(StrEnum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"


class PermissionChoice(StrEnum):
    allowed = "allowed"
    not_allowed = "not_allowed"
    unclear = "unclear"


class ReleaseChoice(StrEnum):
    internal = "internal"
    public = "public"


RepoRootOption = Annotated[
    Path | None,
    typer.Option(
        "--repo-root",
        envvar="OPENINSPECT_REPO_ROOT",
        file_okay=False,
        help="Repository root (default: nearest parent that contains manifests/sources).",
    ),
]
JsonOption = Annotated[bool, typer.Option("--json", help="Machine-readable JSON output.")]


# ----------------------------------------------------------------------------- helpers


def _root(repo_root: Path | None) -> Path:
    return repo_root.resolve() if repo_root is not None else find_repo_root()


def _err(message: str) -> None:
    typer.echo(message, err=True)


def _fail(message: str, code: int = 1) -> NoReturn:
    _err(f"ERROR {message}")
    raise typer.Exit(code=code)


def _format_issue(issue: Issue) -> str:
    tag = "ERROR" if issue.level == "error" else "WARN "
    slug = f" [{issue.slug}]" if issue.slug else ""
    return f"{tag} {issue.code}{slug} {issue.message}"


def _echo_json(payload: object) -> None:
    typer.echo(json.dumps(payload, indent=2, ensure_ascii=True))


def _require_allowlist(root: Path) -> LicenceAllowlist:
    try:
        return load_allowlist(root / LICENCES_PATH)
    except LicenceConfigError as exc:
        _fail(f"E_LICENCE_CONFIG {exc}")


def _table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [max(len(header), *(len(row[i]) for row in rows)) for i, header in enumerate(headers)]
    line = "  ".join(header.ljust(width) for header, width in zip(headers, widths, strict=True))
    body = [
        "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True))
        for row in rows
    ]
    return "\n".join([line.rstrip(), *(row.rstrip() for row in body)])


def _dash(value: object) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    return "-" if value is None or value == "" or value == [] else str(value)


def _summary(item: LoadedManifest) -> dict[str, Any]:
    manifest = item.manifest
    return {
        "slug": manifest.slug,
        "dataset_name": manifest.dataset_name,
        "status": manifest.status,
        "licence": manifest.licence.spdx,
        "version": manifest.identity.version,
        "usable_for_ingest": manifest.usable_for_ingest,
        "public_release_allowed": manifest.public_release_allowed,
        "images": manifest.content.image_count,
    }


# ------------------------------------------------------------------------------- list


@source_app.command("list")
def list_sources(
    status: Annotated[
        StatusChoice | None, typer.Option("--status", help="Only sources with this status.")
    ] = None,
    as_json: JsonOption = False,
    repo_root: RepoRootOption = None,
) -> None:
    """List registered sources: slug, status, licence, version, public-release flag, images."""
    root = _root(repo_root)
    registry = load_registry(root)
    items = [
        item for item in registry.loaded if status is None or item.manifest.status == status.value
    ]
    records = [_summary(item) for item in items]
    if as_json:
        _echo_json({"sources": records, "errors": [issue.as_dict() for issue in registry.issues]})
    else:
        if records:
            rows = [
                [
                    str(r["slug"]),
                    str(r["status"]),
                    _dash(r["licence"]),
                    _dash(r["version"]),
                    "yes" if r["public_release_allowed"] else "no",
                    _dash(r["images"]),
                ]
                for r in records
            ]
            typer.echo(_table(["SLUG", "STATUS", "LICENCE", "VERSION", "PUBLIC", "IMAGES"], rows))
        else:
            typer.echo("No sources registered.")
        for issue in registry.issues:
            _err(_format_issue(issue))
    if any(issue.level == "error" for issue in registry.issues):
        raise typer.Exit(code=1)


# ------------------------------------------------------------------------------- show


def _show_text(item: LoadedManifest, root: Path) -> str:
    manifest = item.manifest
    identity, licence, decision, content = (
        manifest.identity,
        manifest.licence,
        manifest.decision,
        manifest.content,
    )
    blockers = manifest.public_release_blockers()
    lines = [
        f"{manifest.slug}  [{manifest.status}]",
        f"  {manifest.dataset_name}",
        f"  file: {rel_path(item.path, root)}",
    ]

    def section(title: str, rows: list[tuple[str, object]]) -> None:
        width = max(len(key) for key, _ in rows)
        lines.append("")
        lines.append(title)
        lines.extend(f"  {key.ljust(width)} : {_dash(value)}" for key, value in rows)

    section(
        "Identity",
        [
            ("official_url", identity.official_url),
            ("doi", identity.doi),
            ("version", identity.version),
            ("creators", len(identity.creators) or None),
            ("original upload", identity.is_original_upload),
        ],
    )
    section(
        "Licence",
        [
            ("spdx", licence.spdx),
            ("licence_url", licence.licence_url),
            ("redistribution", licence.redistribution),
            ("derivative_work", licence.derivative_work),
            ("commercial_use", licence.commercial_use),
            ("attribution", licence.attribution_required),
            ("verified_on", licence.verified_on),
            (
                "evidence archived",
                f"{len(manifest.archived_evidence_paths())} of {len(licence.evidence)}",
            ),
            ("conflicts", len(licence.conflicts) or None),
        ],
    )
    section(
        "Decision",
        [
            ("status", decision.status),
            ("decided_by", decision.decided_by),
            ("decided_on", decision.decided_on),
            ("reason", decision.reason),
        ],
    )
    section(
        "Content",
        [
            ("domain", content.domain),
            ("task", content.task),
            ("images", content.image_count),
            ("annotations", content.annotation_count),
            ("classes", ", ".join(c.label for c in content.original_classes)),
        ],
    )
    section(
        "Computed",
        [
            ("usable_for_ingest", "yes" if manifest.usable_for_ingest else "no"),
            ("public_release", "yes" if not blockers else "no (" + "; ".join(blockers) + ")"),
        ],
    )
    return "\n".join(lines)


@source_app.command("show")
def show(
    slug: Annotated[str, typer.Argument(help="Source id.")],
    as_json: JsonOption = False,
    repo_root: RepoRootOption = None,
) -> None:
    """Show one source: identity, licence, decision, content and the computed release flags."""
    root = _root(repo_root)
    registry = load_registry(root)
    item = registry.get(slug)
    if item is None:
        known = ", ".join(registry.slugs) or "none"
        for issue in registry.issues:
            _err(_format_issue(issue))
        _fail(f"E_UNKNOWN_SLUG no source with slug {slug!r} (known: {known})")
    if as_json:
        manifest = item.manifest
        _echo_json(
            {
                "manifest": manifest.model_dump(mode="json"),
                "computed": {
                    "file": rel_path(item.path, root),
                    "usable_for_ingest": manifest.usable_for_ingest,
                    "public_release_allowed": manifest.public_release_allowed,
                    "public_release_blockers": manifest.public_release_blockers(),
                },
            }
        )
    else:
        typer.echo(_show_text(item, root))


# -------------------------------------------------------------------------------- add


def _drop_none(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None}


def _print_issues_and_exit(issues: list[Issue]) -> NoReturn:
    for issue in issues:
        _err(_format_issue(issue))
    raise typer.Exit(code=1)


def _manifest_from_file(path: Path) -> SourceManifest:
    manifest, issues = parse_manifest_text(path.read_text(encoding="utf-8"), path.as_posix())
    if manifest is None:
        _print_issues_and_exit(issues)
    return manifest


def _manifest_from_flags(
    *,
    slug: str | None,
    name: str | None,
    status: StatusChoice,
    official_url: str | None,
    doi: str | None,
    record_version: str | None,
    licence: str | None,
    licence_url: str | None,
    redistribution: PermissionChoice | None,
    derivative_work: PermissionChoice | None,
    commercial_use: PermissionChoice | None,
    reason: str | None,
    decided_by: str,
) -> SourceManifest:
    if slug is None or name is None:
        _fail("give a SLUG and --name, or import a complete manifest with --from-file", code=2)
    if reason is not None and status is not StatusChoice.rejected:
        _fail("--reason is only used together with --status rejected", code=2)
    if status is StatusChoice.accepted:
        _fail(
            "E_ACCEPTED_NEEDS_FILE an accepted source needs archived evidence and a complete "
            "decision block: write the manifest and import it with --from-file"
        )
    data: dict[str, Any] = {
        "schema_version": 1,
        "slug": slug,
        "dataset_name": name,
        "status": status.value,
        "identity": _drop_none(
            {"official_url": official_url, "doi": doi, "version": record_version}
        ),
        "licence": _drop_none(
            {
                "spdx": licence,
                "licence_url": licence_url,
                "redistribution": redistribution.value if redistribution else None,
                "derivative_work": derivative_work.value if derivative_work else None,
                "commercial_use": commercial_use.value if commercial_use else None,
            }
        ),
    }
    if status is StatusChoice.rejected:
        data["decision"] = {
            "status": "rejected",
            "decided_by": decided_by,
            "decided_on": date.today(),
            "reason": reason,
        }
    try:
        return SourceManifest.model_validate(data)
    except ValidationError as exc:
        _print_issues_and_exit(schema_issues(exc, slug, None))


def _check_rules(manifest: SourceManifest, root: Path) -> None:
    """Allowlist and evidence rules for a manifest that is about to be written."""
    issues: list[Issue] = []
    if manifest.status == "accepted":
        issues.extend(validate_manifest(manifest, allowlist=_require_allowlist(root)))
    if manifest.archived_evidence_paths():
        path = manifests_dir_for(root) / f"{manifest.slug}.yaml"
        issues.extend(verify_evidence(root, [LoadedManifest(path, manifest)], whole_archive=False))
    if any(issue.level == "error" for issue in issues):
        _print_issues_and_exit(issues)
    for issue in issues:
        _err(_format_issue(issue))


@source_app.command("add")
def add(
    slug: Annotated[
        str | None,
        typer.Argument(help="Source id: the file name and `source_dataset` in image records."),
    ] = None,
    name: Annotated[str | None, typer.Option("--name", help="Dataset name.")] = None,
    from_file: Annotated[
        Path | None,
        typer.Option(
            "--from-file",
            exists=True,
            dir_okay=False,
            readable=True,
            help="Import a complete manifest (any status) instead of describing one with flags.",
        ),
    ] = None,
    official_url: Annotated[str | None, typer.Option("--official-url")] = None,
    doi: Annotated[
        str | None, typer.Option("--doi", help="Bare DOI, e.g. 10.5281/zenodo.123.")
    ] = None,
    record_version: Annotated[str | None, typer.Option("--record-version")] = None,
    licence: Annotated[
        str | None, typer.Option("--licence", help="SPDX id, e.g. CC-BY-4.0.")
    ] = None,
    licence_url: Annotated[str | None, typer.Option("--licence-url")] = None,
    redistribution: Annotated[PermissionChoice | None, typer.Option("--redistribution")] = None,
    derivative_work: Annotated[PermissionChoice | None, typer.Option("--derivative-work")] = None,
    commercial_use: Annotated[PermissionChoice | None, typer.Option("--commercial-use")] = None,
    status: Annotated[
        StatusChoice,
        typer.Option("--status", help="pending (default) or rejected; accepted needs --from-file."),
    ] = StatusChoice.pending,
    reason: Annotated[
        str | None, typer.Option("--reason", help="Why the source is rejected (required then).")
    ] = None,
    decided_by: Annotated[str, typer.Option("--decided-by")] = "project-maintainer",
    force: Annotated[
        bool, typer.Option("--force", help="Replace an existing file with the same slug.")
    ] = False,
    repo_root: RepoRootOption = None,
) -> None:
    """Register a source: pending or rejected from flags, or a complete manifest from a file."""
    root = _root(repo_root)
    described = any(
        value is not None
        for value in (
            name,
            official_url,
            doi,
            record_version,
            licence,
            licence_url,
            redistribution,
            derivative_work,
            commercial_use,
            reason,
        )
    )
    if from_file is not None:
        if described or status is not StatusChoice.pending:
            _fail("use either --from-file or the descriptive flags, not both", code=2)
        manifest = _manifest_from_file(from_file)
        if slug is not None and slug != manifest.slug:
            _fail(f"the file declares slug {manifest.slug!r}, not {slug!r}")
    else:
        manifest = _manifest_from_flags(
            slug=slug,
            name=name,
            status=status,
            official_url=official_url,
            doi=doi,
            record_version=record_version,
            licence=licence,
            licence_url=licence_url,
            redistribution=redistribution,
            derivative_work=derivative_work,
            commercial_use=commercial_use,
            reason=reason,
            decided_by=decided_by,
        )
    _check_rules(manifest, root)
    try:
        target = add_manifest(root, manifest, force=force)
    except DuplicateSourceError as exc:
        _fail(f"E_DUPLICATE_SLUG {exc}")
    typer.echo(f"Created {rel_path(target, root)} (status: {manifest.status})")
    if manifest.status == "pending":
        typer.echo(
            "Next: fill in the manifest, archive the evidence, "
            "then run `openinspect source validate`."
        )


# ---------------------------------------------------------------------------- validate


@source_app.command("validate")
def validate(
    slugs: Annotated[
        list[str] | None, typer.Argument(help="Sources to validate (default: all).")
    ] = None,
    release: Annotated[
        ReleaseChoice,
        typer.Option(
            "--release",
            help="'public' also fails for accepted sources that cannot be redistributed.",
        ),
    ] = ReleaseChoice.internal,
    check_evidence: Annotated[
        bool,
        typer.Option(
            "--check-evidence/--no-check-evidence",
            help="Verify archived evidence hashes and manifests/evidence/SHA256SUMS.txt.",
        ),
    ] = True,
    strict: Annotated[bool, typer.Option("--strict", help="Treat warnings as errors.")] = False,
    as_json: JsonOption = False,
    repo_root: RepoRootOption = None,
) -> None:
    """Validate manifests: schema, allowlist, evidence hashes, slugs, public-release rules."""
    root = _root(repo_root)
    allowlist = _require_allowlist(root)
    registry = load_registry(root)
    issues = validate_registry(
        registry,
        allowlist,
        check_evidence=check_evidence,
        release=release.value,
        only=slugs or None,
    )
    errors = [issue for issue in issues if issue.level == "error"]
    warnings = [issue for issue in issues if issue.level == "warning"]
    failed = bool(errors) or (strict and bool(warnings))
    checked = sorted(set(slugs)) if slugs else registry.slugs
    if as_json:
        _echo_json(
            {
                "ok": not failed,
                "release": release.value,
                "evidence_checked": check_evidence,
                "checked": checked,
                "errors": len(errors),
                "warnings": len(warnings),
                "issues": [issue.as_dict() for issue in issues],
            }
        )
    else:
        evidence_note = "checked" if check_evidence else "not checked"
        typer.echo(
            f"Checked {len(checked)} source(s) against {LICENCES_PATH.as_posix()} "
            f"(release: {release.value}, evidence: {evidence_note})"
        )
        for issue in issues:
            typer.echo(_format_issue(issue))
        verdict = "FAILED" if failed else "OK"
        typer.echo(f"Result: {len(errors)} error(s), {len(warnings)} warning(s) -> {verdict}")
    if failed:
        raise typer.Exit(code=1)
