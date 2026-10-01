from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from openinspect.cli import app
from openinspect.readiness.models import Readiness
from openinspect.readiness.run import Outputs, RunError
from tests.conftest import Repo

REAL = Path(__file__).resolve().parents[2]


def committed() -> Readiness:
    return Readiness.model_validate_json(
        (REAL / "artifacts" / "m5_5" / "readiness.json").read_text(encoding="utf-8")
    )


def test_compute_writes_files_readiness_and_reports(
    repo: Repo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = tmp_path / "data"
    data.mkdir()

    def fake(*_: object, **__: object) -> Outputs:
        return Outputs({"artifacts/m5_5/extra.csv": b"a\n"}, committed())

    monkeypatch.setattr("openinspect.cli.readiness.compute", fake)
    result = repo.cli("readiness", "compute", "--data-dir", str(data))
    assert result.exit_code == 0, result.output
    assert (repo.root / "artifacts" / "m5_5" / "extra.csv").read_bytes() == b"a\n"
    assert (repo.root / "artifacts" / "m5_5" / "readiness.json").is_file()
    assert (repo.root / "reports" / "m5_5" / "TRAINING_READINESS.md").is_file()
    assert f"verdict: {committed().verdict}" in result.output


def test_compute_reports_a_failed_step(
    repo: Repo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = tmp_path / "data"
    data.mkdir()

    def broken(*_: object, **__: object) -> Outputs:
        raise RunError("the committed M5 splits do not reproduce")

    monkeypatch.setattr("openinspect.cli.readiness.compute", broken)
    result = repo.cli("readiness", "compute", "--data-dir", str(data))
    assert result.exit_code == 1
    assert "do not reproduce" in result.output


def test_report_and_check_run_on_the_committed_repository(tmp_path: Path) -> None:
    runner = CliRunner()
    checked = runner.invoke(app, ["readiness", "check", "--repo-root", str(REAL)])
    assert checked.exit_code == 0, checked.output
    assert "re-derive" in checked.output
    copy = tmp_path / "copy"
    (copy / "artifacts" / "m5_5").mkdir(parents=True)
    shutil.copy(REAL / "artifacts" / "m5_5" / "readiness.json", copy / "artifacts" / "m5_5")
    rendered = runner.invoke(app, ["readiness", "report", "--repo-root", str(copy)])
    assert rendered.exit_code == 0, rendered.output
    assert (copy / "reports" / "m5_5" / "m7-plan.md").is_file()


def test_check_and_report_fail_without_the_artifact(tmp_path: Path) -> None:
    runner = CliRunner()
    for command in ("check", "report"):
        result = runner.invoke(app, ["readiness", command, "--repo-root", str(tmp_path)])
        assert result.exit_code == 1
        assert "cannot read" in result.output


def test_check_reports_a_changed_input(tmp_path: Path) -> None:
    from openinspect.readiness.check import check_committed

    readiness = committed()
    problems = check_committed(tmp_path, readiness)  # nothing is there: every input "changed"
    assert problems
    assert all("changed since M5.5 ran" in p or "does not match" in p for p in problems)
