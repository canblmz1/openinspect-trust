from __future__ import annotations

from pathlib import Path

import pytest

from openinspect.provenance.licences import LicenceConfigError, load_allowlist
from tests.conftest import Repo

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_the_committed_allowlist_loads_and_holds_the_v01_licences() -> None:
    allowlist = load_allowlist(REPO_ROOT / "configs" / "licences.yaml")
    assert {item.spdx for item in allowlist.allowlist} == {"CC0-1.0", "CC-BY-4.0"}


def test_allowed_ids_are_compared_case_insensitively(repo: Repo) -> None:
    allowlist = load_allowlist(repo.root / "configs" / "licences.yaml")
    assert allowlist.is_allowed("CC-BY-4.0")
    assert allowlist.is_allowed("cc-by-4.0")
    assert not allowlist.is_allowed("CC-BY-4.1")


@pytest.mark.parametrize(
    ("spdx", "fragment"),
    [
        ("CC-BY-NC-4.0", "non-commercial"),
        ("CC-BY-ND-4.0", "no-derivatives"),
        ("CC-BY-SA-4.0", "share-alike"),
        ("CC-BY-NC-SA-4.0", "non-commercial"),
    ],
)
def test_nc_nd_and_sa_licences_are_blocked_with_a_reason(
    repo: Repo, spdx: str, fragment: str
) -> None:
    allowlist = load_allowlist(repo.root / "configs" / "licences.yaml")
    assert not allowlist.is_allowed(spdx)
    reason = allowlist.blocked_reason(spdx)
    assert reason is not None
    assert fragment in reason


def test_an_unlisted_licence_is_not_allowed_but_not_blocked_either(repo: Repo) -> None:
    allowlist = load_allowlist(repo.root / "configs" / "licences.yaml")
    assert not allowlist.is_allowed("MIT")
    assert allowlist.blocked_reason("MIT") is None
    assert allowlist.blocked_reason("CC0-1.0") is None


def test_a_missing_file_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(LicenceConfigError, match="cannot read"):
        load_allowlist(tmp_path / "nope.yaml")


def test_invalid_yaml_is_a_config_error(tmp_path: Path) -> None:
    path = tmp_path / "licences.yaml"
    path.write_text("allowlist: [", encoding="utf-8")
    with pytest.raises(LicenceConfigError, match="invalid YAML"):
        load_allowlist(path)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "schema_version: 1\nallowlist: []\n",
        "schema_version: 2\nallowlist:\n  - {spdx: CC0-1.0, name: x, url: https://x.org}\n",
        "schema_version: 1\nallowlist:\n  - {spdx: CC0-1.0, name: x}\n",
    ],
)
def test_a_malformed_allowlist_is_a_config_error(tmp_path: Path, text: str) -> None:
    path = tmp_path / "licences.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(LicenceConfigError, match="invalid licence allowlist"):
        load_allowlist(path)
