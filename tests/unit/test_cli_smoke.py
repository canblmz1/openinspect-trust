"""`openinspect release smoke-verify` and `smoke-report` on a copy of the committed M6 inputs."""

from __future__ import annotations

import shutil
from pathlib import Path

from typer.testing import CliRunner

from openinspect.cli import app

REAL = Path(__file__).resolve().parents[2]
INPUTS = (
    "configs/release.yaml",
    "manifests/releases/v0.1/annotations.parquet",
    "manifests/releases/v0.1/evren-smoke/observed.yaml",
    "manifests/releases/v0.1/evren-smoke/expected-splits.csv",
    "manifests/releases/v0.1/evren-smoke/smoke.json",
)
REPORT = "reports/m6/evren-smoke-test.md"


def copy_inputs(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    for rel in INPUTS:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REAL / rel, root / rel)
    return root


def test_smoke_verify_passes_and_smoke_report_renders_the_same_report(tmp_path: Path) -> None:
    root = copy_inputs(tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    runner = CliRunner()
    verified = runner.invoke(
        app, ["release", "smoke-verify", "--repo-root", str(root), "--data-dir", str(data)]
    )
    assert verified.exit_code == 0, verified.output
    assert "M6 verdict: PASS" in verified.output
    assert (root / "artifacts" / "m6" / "evren-smoke-test.json").is_file()
    report = (root / REPORT).read_text(encoding="utf-8")
    assert "the ZIP is not re-checked" in verified.output  # no ZIP in this data directory
    (root / REPORT).unlink()
    rendered = runner.invoke(app, ["release", "smoke-report", "--repo-root", str(root)])
    assert rendered.exit_code == 0, rendered.output
    assert (root / REPORT).read_text(encoding="utf-8") == report


def test_smoke_report_needs_the_record(tmp_path: Path) -> None:
    root = copy_inputs(tmp_path)
    result = CliRunner().invoke(app, ["release", "smoke-report", "--repo-root", str(root)])
    assert result.exit_code == 1
    assert "cannot read" in result.output


def test_smoke_verify_fails_on_a_changed_observation(tmp_path: Path) -> None:
    root = copy_inputs(tmp_path)
    observed = root / "manifests/releases/v0.1/evren-smoke/observed.yaml"
    text = observed.read_text(encoding="utf-8")
    assert "auto_split_used: false" in text
    observed.write_text(text.replace("auto_split_used: false", "auto_split_used: true"), "utf-8")
    data = tmp_path / "data"
    data.mkdir()
    result = CliRunner().invoke(
        app, ["release", "smoke-verify", "--repo-root", str(root), "--data-dir", str(data)]
    )
    assert result.exit_code == 1
    assert "M6 verdict: FAIL" in result.output
