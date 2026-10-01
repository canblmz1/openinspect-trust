"""``openinspect readiness compute | report | check``: training readiness (Milestone 5.5)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from openinspect.cli.common import DataDirOption, RepoRootOption, fail, log, setup
from openinspect.dedup.perf import code_version
from openinspect.files import replace_bytes
from openinspect.provenance.registry import find_repo_root
from openinspect.readiness.check import check_committed
from openinspect.readiness.models import Readiness
from openinspect.readiness.pipeline import ARTIFACTS
from openinspect.readiness.report import write_reports
from openinspect.readiness.run import RunError, compute
from openinspect.release.manifest import json_bytes

readiness_app = typer.Typer(
    help="Training readiness: controlled designs, representation sensitivity, label findings, "
    "source probe, held-out regimes and independent export validation.",
    no_args_is_help=True,
)

READINESS = ARTIFACTS / "readiness.json"


def read_readiness(root: Path) -> Readiness:
    try:
        return Readiness.model_validate_json((root / READINESS).read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        fail(f"cannot read {READINESS.as_posix()}: {exc}")


@readiness_app.command("compute")
def compute_command(
    ultralytics_python: Annotated[
        Path | None,
        typer.Option(
            "--ultralytics-python",
            dir_okay=False,
            help="Python of a separate environment with Ultralytics, for the independent export check.",
        ),
    ] = None,
    threads: Annotated[int | None, typer.Option("--threads", min=1)] = None,
    packages: Annotated[
        list[str] | None,
        typer.Option(
            "--package", help="Build and validate only this scheme's package (repeatable)."
        ),
    ] = None,
    data_dir: DataDirOption = None,
    repo_root: RepoRootOption = None,
) -> None:
    """Run every M5.5 step and write the artifacts, split files and reports (needs the data)."""
    root, data, _ = setup(repo_root, data_dir)
    code = code_version(root)  # the code of this process was loaded at its start
    try:
        outputs = compute(
            root,
            data,
            ultralytics_python=ultralytics_python,
            threads=threads,
            log=log,
            code=code,
            packages=packages,
        )
    except (RunError, OSError, KeyError, ValueError) as exc:
        fail(str(exc))
    for path, blob in outputs.files.items():
        replace_bytes(root / path, blob)
    replace_bytes(root / READINESS, json_bytes(outputs.readiness.model_dump(mode="json")))
    for written in write_reports(root, outputs.readiness):
        typer.echo(f"report: {written.relative_to(root).as_posix()}")
    typer.echo(f"verdict: {outputs.readiness.verdict}")
    for blocker in outputs.readiness.blockers:
        typer.echo(f"BLOCKER {blocker}", err=True)


@readiness_app.command("report")
def report_command(repo_root: RepoRootOption = None) -> None:
    """Re-render reports/m5_5/ from artifacts/m5_5/readiness.json (no data needed)."""
    root = repo_root.resolve() if repo_root is not None else find_repo_root()
    for path in write_reports(root, read_readiness(root)):
        typer.echo(f"report: {path.relative_to(root).as_posix()}")


@readiness_app.command("check")
def check_command(repo_root: RepoRootOption = None) -> None:
    """Re-derive the M5.5 splits and tables from committed files and compare (no data needed)."""
    root = repo_root.resolve() if repo_root is not None else find_repo_root()
    problems = check_committed(root, read_readiness(root))
    for problem in problems:
        typer.echo(f"PROBLEM {problem}", err=True)
    if problems:
        fail(f"{len(problems)} problems")
    typer.echo("readiness: the committed M5.5 outputs re-derive from the committed inputs")
