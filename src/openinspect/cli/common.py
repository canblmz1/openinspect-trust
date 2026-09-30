"""Options and helpers shared by the ``openinspect`` command groups."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, NoReturn

import typer

from openinspect.provenance.registry import LoadedManifest, Registry, find_repo_root, load_registry
from openinspect.settings import DataDirError, resolve_data_dir

RepoRootOption = Annotated[
    Path | None,
    typer.Option(
        "--repo-root", envvar="OPENINSPECT_REPO_ROOT", file_okay=False, help="Repository root."
    ),
]
DataDirOption = Annotated[
    Path | None,
    typer.Option(
        "--data-dir",
        file_okay=False,
        help="Data directory (default: $OPENINSPECT_DATA_DIR, then .env); not in the repo or OneDrive.",
    ),
]
AllOption = Annotated[bool, typer.Option("--all", help="All accepted sources.")]
SlugsArgument = Annotated[list[str] | None, typer.Argument(help="Source ids.")]


def fail(message: str) -> NoReturn:
    typer.echo(f"ERROR {message}", err=True)
    raise typer.Exit(code=1)


def log(message: str) -> None:
    typer.echo(message, err=True)


def setup(repo_root: Path | None, data_dir: Path | None) -> tuple[Path, Path, Registry]:
    root = repo_root.resolve() if repo_root is not None else find_repo_root()
    try:
        data = resolve_data_dir(data_dir, repo_root=root)
    except DataDirError as exc:
        fail(str(exc))
    registry = load_registry(root)
    if any(issue.level == "error" for issue in registry.issues):
        for issue in registry.issues:
            typer.echo(f"{issue.code} {issue.message}", err=True)
        fail("the source registry has errors; run `openinspect source validate`")
    return root, data, registry


def select_sources(
    registry: Registry, slugs: list[str] | None, all_sources: bool
) -> list[LoadedManifest]:
    if all_sources:
        chosen = [lm for lm in registry.loaded if lm.manifest.usable_for_ingest]
    else:
        if not slugs:
            fail("name at least one source, or pass --all")
        chosen = []
        for slug in slugs:
            item = registry.get(slug)
            if item is None:
                fail(f"no source with slug {slug!r} (known: {', '.join(registry.slugs)})")
            if not item.manifest.usable_for_ingest:
                fail(
                    f"source {slug!r} is {item.manifest.status}: "
                    "only accepted sources may be ingested"
                )
            chosen.append(item)
    if not chosen:
        fail("no accepted source selected")
    return chosen
