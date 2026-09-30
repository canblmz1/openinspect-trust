from __future__ import annotations

from pathlib import Path

import pytest

from openinspect import settings
from openinspect.settings import (
    DataDirError,
    check_data_dir,
    ensure_free_space,
    parse_dotenv,
    resolve_data_dir,
)


def test_parse_dotenv_reads_plain_quoted_and_ignores_noise() -> None:
    text = (
        "# comment\n\nA=1\nB = two \nC='quoted value'\nD=\"also\"\nno equals sign\n=novalue\nE=\n"
    )
    assert parse_dotenv(text) == {"A": "1", "B": "two", "C": "quoted value", "D": "also", "E": ""}


def test_explicit_beats_environment_beats_dotenv(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".env").write_text(
        f"OPENINSPECT_DATA_DIR={tmp_path / 'from_dotenv'}\n", encoding="utf-8"
    )
    from_env = tmp_path / "from_env"
    explicit = tmp_path / "explicit"
    env = {"OPENINSPECT_DATA_DIR": str(from_env)}
    assert resolve_data_dir(explicit, repo_root=repo, environ=env) == explicit
    assert resolve_data_dir(None, repo_root=repo, environ=env) == from_env
    assert resolve_data_dir(None, repo_root=repo, environ={}) == tmp_path / "from_dotenv"


def test_a_missing_setting_explains_how_to_set_it(tmp_path: Path) -> None:
    with pytest.raises(DataDirError, match="OPENINSPECT_DATA_DIR is not set"):
        resolve_data_dir(None, repo_root=tmp_path, environ={})


def test_relative_paths_are_refused(tmp_path: Path) -> None:
    with pytest.raises(DataDirError, match="absolute"):
        check_data_dir(Path("data"), repo_root=tmp_path, environ={})


def test_a_path_inside_the_repository_is_refused(tmp_path: Path) -> None:
    with pytest.raises(DataDirError, match="inside the repository"):
        check_data_dir(tmp_path / "data", repo_root=tmp_path, environ={})


def test_a_path_inside_onedrive_is_refused_by_variable_and_by_name(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    onedrive = tmp_path / "OneDrive"
    with pytest.raises(DataDirError, match="inside OneDrive"):
        check_data_dir(onedrive / "x", repo_root=repo, environ={"OneDrive": str(onedrive)})
    with pytest.raises(DataDirError, match="OneDrive folder"):
        check_data_dir(tmp_path / "OneDrive - Acme" / "x", repo_root=repo, environ={})


def test_a_safe_path_passes(tmp_path: Path) -> None:
    check_data_dir(tmp_path / "data", repo_root=tmp_path / "repo", environ={})


def test_free_space_is_checked_against_the_drive_of_the_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Usage:
        free = 5 * settings.GIB

    monkeypatch.setattr("shutil.disk_usage", lambda _path: Usage())
    ensure_free_space(tmp_path / "not" / "yet" / "created", 2 * settings.GIB)
    with pytest.raises(DataDirError, match="not enough free space"):
        ensure_free_space(tmp_path, 10 * settings.GIB)
