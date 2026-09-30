from __future__ import annotations

import json
import subprocess
import sys

import yaml
from typer.testing import CliRunner

from openinspect import __version__
from openinspect.cli import app
from openinspect.provenance.registry import load_registry
from tests.conftest import Repo
from tests.factories import EVIDENCE_REL, accepted_manifest, with_value

FLAGS = (
    "source",
    "add",
    "demo-pending",
    "--name",
    "Demo pending",
    "--official-url",
    "https://example.org/record",
    "--doi",
    "10.1234/abc.1",
    "--licence",
    "CC-BY-4.0",
)


def _row(output: str, slug: str) -> list[str]:
    return next(line for line in output.splitlines() if line.startswith(slug)).split()


# ------------------------------------------------------------------ entry points


def test_version_flag() -> None:
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"openinspect {__version__}"


def test_help_lists_the_source_commands() -> None:
    result = CliRunner().invoke(app, ["source", "--help"])
    assert result.exit_code == 0
    for command in ("add", "list", "show", "validate"):
        assert command in result.output


def test_python_dash_m_entry_point() -> None:
    done = subprocess.run(
        [sys.executable, "-m", "openinspect", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0
    assert done.stdout.strip() == f"openinspect {__version__}"


# ------------------------------------------------------------------------- add


def test_add_an_accepted_manifest_from_a_file(repo: Repo) -> None:
    incoming = repo.write_file("incoming.yaml", accepted_manifest())
    result = repo.cli("source", "add", "--from-file", str(incoming))
    assert result.exit_code == 0, result.output
    assert "Created manifests/sources/demo-source.yaml (status: accepted)" in result.output
    assert (repo.sources / "demo-source.yaml").is_file()


def test_accepted_source_is_listed_and_shown(repo: Repo) -> None:
    repo.cli(
        "source", "add", "--from-file", str(repo.write_file("incoming.yaml", accepted_manifest()))
    )
    listed = repo.cli("source", "list")
    assert listed.exit_code == 0
    assert _row(listed.output, "demo-source") == [
        "demo-source",
        "accepted",
        "CC-BY-4.0",
        "v1",
        "yes",
        "10",
    ]
    shown = repo.cli("source", "show", "demo-source")
    assert shown.exit_code == 0
    assert "demo-source  [accepted]" in shown.output
    assert "CC-BY-4.0" in shown.output
    assert "usable_for_ingest : yes" in shown.output
    assert "public_release    : yes" in shown.output


def test_missing_licence_is_rejected_and_nothing_is_written(repo: Repo) -> None:
    data = with_value(accepted_manifest(), "licence.spdx", None)
    result = repo.cli("source", "add", "--from-file", str(repo.write_file("incoming.yaml", data)))
    assert result.exit_code == 1
    assert "licence.spdx is missing" in result.output
    assert not (repo.sources / "demo-source.yaml").exists()


def test_missing_source_url_is_rejected(repo: Repo) -> None:
    data = with_value(accepted_manifest(), "identity.official_url", None)
    result = repo.cli("source", "add", "--from-file", str(repo.write_file("incoming.yaml", data)))
    assert result.exit_code == 1
    assert "identity.official_url is missing" in result.output


def test_invalid_doi_is_a_validation_error(repo: Repo) -> None:
    data = with_value(accepted_manifest(), "identity.doi", "https://doi.org/10.5281/zenodo.1")
    result = repo.cli("source", "add", "--from-file", str(repo.write_file("incoming.yaml", data)))
    assert result.exit_code == 1
    assert "invalid DOI" in result.output


def test_an_accepted_licence_outside_the_allowlist_is_refused(repo: Repo) -> None:
    data = with_value(accepted_manifest(), "licence.spdx", "CC-BY-NC-4.0")
    result = repo.cli("source", "add", "--from-file", str(repo.write_file("incoming.yaml", data)))
    assert result.exit_code == 1
    assert "E_LICENCE_NOT_ALLOWED" in result.output
    assert not (repo.sources / "demo-source.yaml").exists()


def test_tampered_evidence_is_refused_at_add_time(repo: Repo) -> None:
    (repo.root / EVIDENCE_REL).write_bytes(b"tampered")
    result = repo.cli(
        "source", "add", "--from-file", str(repo.write_file("incoming.yaml", accepted_manifest()))
    )
    assert result.exit_code == 1
    assert "E_EVIDENCE_HASH_MISMATCH" in result.output


def test_duplicate_source_id_is_rejected(repo: Repo) -> None:
    assert repo.cli(*FLAGS).exit_code == 0
    again = repo.cli(*FLAGS)
    assert again.exit_code == 1
    assert "E_DUPLICATE_SLUG" in again.output
    assert "already exists" in again.output
    assert repo.cli(*FLAGS, "--force").exit_code == 0


def test_add_a_pending_source_from_flags(repo: Repo) -> None:
    result = repo.cli(*FLAGS)
    assert result.exit_code == 0, result.output
    assert "Created manifests/sources/demo-pending.yaml (status: pending)" in result.output
    loaded = load_registry(repo.root).get("demo-pending")
    assert loaded is not None
    assert loaded.manifest.identity.official_url == "https://example.org/record"
    assert loaded.manifest.licence.spdx == "CC-BY-4.0"
    assert repo.cli("source", "validate", "--no-check-evidence").exit_code == 0
    assert _row(repo.cli("source", "list").output, "demo-pending")[1] == "pending"


def test_an_accepted_source_cannot_be_created_from_flags(repo: Repo) -> None:
    result = repo.cli("source", "add", "demo-x", "--name", "X", "--status", "accepted")
    assert result.exit_code == 1
    assert "--from-file" in result.output


def test_a_rejected_source_needs_a_reason(repo: Repo) -> None:
    missing = repo.cli("source", "add", "demo-no", "--name", "No", "--status", "rejected")
    assert missing.exit_code == 1
    assert "decision.reason is missing" in missing.output
    ok = repo.cli(
        "source",
        "add",
        "demo-no",
        "--name",
        "No",
        "--status",
        "rejected",
        "--reason",
        "Unclear licence.",
    )
    assert ok.exit_code == 0, ok.output
    shown = repo.cli("source", "show", "demo-no")
    assert "[rejected]" in shown.output
    assert "Unclear licence." in shown.output


def test_an_invalid_doi_from_flags_is_a_validation_error(repo: Repo) -> None:
    result = repo.cli("source", "add", "demo-doi", "--name", "D", "--doi", "not-a-doi")
    assert result.exit_code == 1
    assert "invalid DOI" in result.output


def test_add_needs_a_slug_and_a_name(repo: Repo) -> None:
    assert repo.cli("source", "add", "only-a-slug").exit_code == 2
    assert repo.cli("source", "add").exit_code == 2


def test_reason_belongs_to_rejected_sources_only(repo: Repo) -> None:
    result = repo.cli("source", "add", "demo-r", "--name", "R", "--reason", "because")
    assert result.exit_code == 2


def test_file_and_flags_cannot_be_mixed(repo: Repo) -> None:
    incoming = repo.write_file("incoming.yaml", accepted_manifest())
    result = repo.cli("source", "add", "--from-file", str(incoming), "--name", "Other")
    assert result.exit_code == 2


def test_the_slug_argument_must_match_the_file(repo: Repo) -> None:
    incoming = repo.write_file("incoming.yaml", accepted_manifest())
    result = repo.cli("source", "add", "another-slug", "--from-file", str(incoming))
    assert result.exit_code == 1
    assert "declares slug" in result.output


def test_a_missing_import_file_is_a_usage_error(repo: Repo) -> None:
    assert repo.cli("source", "add", "--from-file", str(repo.root / "nope.yaml")).exit_code == 2


def test_an_unreadable_import_file_reports_the_yaml_problem(repo: Repo) -> None:
    broken = repo.root / "broken.yaml"
    broken.write_text("a: [1, 2", encoding="utf-8")
    result = repo.cli("source", "add", "--from-file", str(broken))
    assert result.exit_code == 1
    assert "E_YAML" in result.output


# ------------------------------------------------------------------------ list


def test_list_on_an_empty_registry(repo: Repo) -> None:
    result = repo.cli("source", "list")
    assert result.exit_code == 0
    assert "No sources registered." in result.output


def test_list_filters_by_status_and_can_print_json(repo: Repo) -> None:
    repo.write_manifest(accepted_manifest())
    repo.cli(*FLAGS)
    accepted = repo.cli("source", "list", "--status", "accepted")
    assert "demo-source" in accepted.output
    assert "demo-pending" not in accepted.output
    payload = json.loads(repo.cli("source", "list", "--json").output)
    assert {s["slug"] for s in payload["sources"]} == {"demo-source", "demo-pending"}
    assert payload["errors"] == []


def test_list_shows_the_good_manifests_but_fails_when_one_is_broken(repo: Repo) -> None:
    repo.write_manifest(accepted_manifest())
    (repo.sources / "broken.yaml").write_text("a: [1", encoding="utf-8")
    result = repo.cli("source", "list")
    assert result.exit_code == 1
    assert "demo-source" in result.output
    assert "E_YAML" in result.output


# ------------------------------------------------------------------------ show


def test_show_prints_json(repo: Repo) -> None:
    repo.write_manifest(accepted_manifest())
    payload = json.loads(repo.cli("source", "show", "demo-source", "--json").output)
    assert payload["manifest"]["slug"] == "demo-source"
    assert payload["computed"]["public_release_allowed"] is True
    assert payload["computed"]["file"] == "manifests/sources/demo-source.yaml"


def test_show_an_unknown_slug_lists_the_known_ones(repo: Repo) -> None:
    repo.write_manifest(accepted_manifest())
    result = repo.cli("source", "show", "nope")
    assert result.exit_code == 1
    assert "E_UNKNOWN_SLUG" in result.output
    assert "demo-source" in result.output


# -------------------------------------------------------------------- validate


def test_validate_passes_on_a_clean_registry(repo: Repo) -> None:
    repo.write_manifest(accepted_manifest())
    result = repo.cli("source", "validate", "--strict")
    assert result.exit_code == 0, result.output
    assert "Result: 0 error(s), 0 warning(s) -> OK" in result.output


def test_unknown_redistribution_permission_blocks_a_public_release(repo: Repo) -> None:
    repo.write_manifest(with_value(accepted_manifest(), "licence.redistribution", "unclear"))
    internal = repo.cli("source", "validate")
    assert internal.exit_code == 0
    assert "W_PUBLIC_RELEASE_BLOCKED" in internal.output
    assert repo.cli("source", "validate", "--strict").exit_code == 1
    public = repo.cli("source", "validate", "--release", "public")
    assert public.exit_code == 1
    assert "E_PUBLIC_RELEASE_BLOCKED" in public.output
    assert "redistribution is unclear" in public.output
    assert _row(repo.cli("source", "list").output, "demo-source")[4] == "no"


def test_validate_detects_tampered_evidence_unless_told_not_to(repo: Repo) -> None:
    repo.write_manifest(accepted_manifest())
    (repo.root / EVIDENCE_REL).write_bytes(b"tampered")
    failed = repo.cli("source", "validate")
    assert failed.exit_code == 1
    assert "E_EVIDENCE_HASH_MISMATCH" in failed.output
    assert repo.cli("source", "validate", "--no-check-evidence").exit_code == 0


def test_duplicate_slug_files_fail_validation(repo: Repo) -> None:
    repo.write_manifest(accepted_manifest(), name="demo-source")
    repo.write_manifest(accepted_manifest(), name="copy")
    result = repo.cli("source", "validate")
    assert result.exit_code == 1
    assert "E_DUPLICATE_SLUG" in result.output


def test_validate_one_source_and_unknown_sources(repo: Repo) -> None:
    repo.write_manifest(accepted_manifest())
    assert repo.cli("source", "validate", "demo-source").exit_code == 0
    unknown = repo.cli("source", "validate", "nope")
    assert unknown.exit_code == 1
    assert "E_UNKNOWN_SLUG" in unknown.output


def test_validate_prints_json(repo: Repo) -> None:
    repo.write_manifest(with_value(accepted_manifest(), "licence.spdx", "MIT"))
    result = repo.cli("source", "validate", "--json")
    payload = json.loads(result.output)
    assert result.exit_code == 1
    assert payload["ok"] is False
    assert payload["errors"] == 1
    assert payload["issues"][0]["code"] == "E_LICENCE_NOT_ALLOWED"
    assert payload["checked"] == ["demo-source"]


def test_a_missing_licence_config_fails_clearly(repo: Repo) -> None:
    (repo.root / "configs" / "licences.yaml").unlink()
    result = repo.cli("source", "validate")
    assert result.exit_code == 1
    assert "E_LICENCE_CONFIG" in result.output


def test_a_written_manifest_is_valid_yaml_a_human_can_read(repo: Repo) -> None:
    repo.cli(
        "source", "add", "--from-file", str(repo.write_file("incoming.yaml", accepted_manifest()))
    )
    text = (repo.sources / "demo-source.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    assert data["slug"] == "demo-source"
    assert data["licence"]["evidence"][0]["archived_path"] == EVIDENCE_REL
