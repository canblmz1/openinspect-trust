"""Top-level ``openinspect`` command."""

from __future__ import annotations

import sys
from typing import Annotated

import typer

from openinspect import __version__
from openinspect.cli.dedup import dedup_app
from openinspect.cli.ingest import ingest_app
from openinspect.cli.source import source_app

app = typer.Typer(
    name="openinspect",
    help="Provenance-aware cross-dataset benchmark tooling for industrial defect detection.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(source_app, name="source")
app.add_typer(ingest_app, name="ingest")
app.add_typer(dedup_app, name="dedup")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"openinspect {__version__}")
        raise typer.Exit()


def _utf8_output() -> None:
    """Never crash on a console whose code page cannot show a character."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):  # pragma: no cover - exotic stream types
                continue


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = False,
) -> None:
    """Provenance-aware cross-dataset benchmark tooling for industrial defect detection."""
    _utf8_output()
