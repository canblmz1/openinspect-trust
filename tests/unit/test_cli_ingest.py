from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import httpx
import pytest

from openinspect.ingest.layout import source_dirs
from openinspect.provenance.registry import load_registry
from openinspect.settings import DataDirError
from tests.conftest import Repo
from tests.factories import accepted_manifest, pending_manifest
from tests.ingest_fixtures import build_pcb_defect, zip_tree

URL = "https://example.org/pcb-defect.zip"


def serve(monkeypatch: pytest.MonkeyPatch, payload: bytes, status: int = 200) -> list[str]:
    """Route the CLI's downloads to an in-memory server; returns the URLs that were requested."""
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(status, content=payload if status == 200 else b"")

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    monkeypatch.setattr("openinspect.cli.ingest._http_client", lambda: client)
    return requested


class Setup:
    def __init__(self, repo: Repo, tmp_path: Path, payload: bytes) -> None:
        self.repo = repo
        self.data = tmp_path / "data"
        self.payload = payload

    def run(self, *args: str, data: Path | None = None) -> Any:
        return self.repo.cli(*args, "--data-dir", str(data or self.data))


@pytest.fixture
def setup(repo: Repo, tmp_path: Path) -> Setup:
    tree = tmp_path / "work"
    build_pcb_defect(tree)
    archive = tmp_path / "pcb-defect.zip"
    zip_tree(tree, archive)
    payload = archive.read_bytes()
    manifest = accepted_manifest("pcb-defect")
    manifest["acquisition"] = {
        "download_method": "http",
        "download_files": [
            {
                "url": URL,
                "filename": "PCB_Defect.zip",
                "bytes": len(payload),
                "record_checksum": {"algo": "sha256", "value": hashlib.sha256(payload).hexdigest()},
            }
        ],
        "download_date": None,
        "archive_sha256": None,
        "sha256_manifest": None,
    }
    repo.write_manifest(manifest)
    return Setup(repo, tmp_path, payload)


def test_download_extract_inspect_run_and_report(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    requested = serve(monkeypatch, setup.payload)
    dirs = source_dirs(setup.data, "pcb-defect")

    downloaded = setup.run("ingest", "download", "pcb-defect")
    assert downloaded.exit_code == 0, downloaded.output
    assert "downloaded, verified" in downloaded.output
    assert requested == [URL]
    assert (dirs.raw / "PCB_Defect.zip").read_bytes() == setup.payload
    record = setup.repo.root / "manifests" / "ingest" / "pcb-defect" / "download.json"
    first_record = record.read_bytes()
    manifest = load_registry(setup.repo.root).get("pcb-defect")
    assert manifest is not None
    assert manifest.manifest.acquisition.download_date is not None
    assert manifest.manifest.acquisition.archive_sha256 == {
        "PCB_Defect.zip": hashlib.sha256(setup.payload).hexdigest()
    }

    again = setup.run("ingest", "download", "pcb-defect")
    assert again.exit_code == 0
    assert "already present, verified" in again.output
    assert requested == [URL]  # nothing was fetched a second time
    assert record.read_bytes() == first_record

    extracted = setup.run("ingest", "extract", "pcb-defect")
    assert extracted.exit_code == 0, extracted.output
    assert "extracted," in extracted.output
    assert "zip CRC-32 ok" in extracted.output
    assert "already extracted" in setup.run("ingest", "extract", "--all").output

    inspected = setup.run("ingest", "inspect", "pcb-defect", "--depth", "2")
    assert inspected.exit_code == 0
    assert "PCB_Defect/images/" in inspected.output
    assert ".jpg x4" in inspected.output

    ran = setup.run("ingest", "run", "--all")
    assert ran.exit_code == 0, ran.output
    assert "4 images (0 undecodable), 5 annotations" in ran.output
    report = setup.repo.root / "reports" / "m2-ingest-report.md"
    assert report.is_file()
    assert "| source | images | annotations | classes |" in report.read_text(encoding="utf-8")
    patched = load_registry(setup.repo.root).get("pcb-defect")
    assert patched is not None
    assert patched.manifest.acquisition.sha256_manifest == "manifests/ingest/pcb-defect/report.json"
    assert setup.repo.cli("source", "validate", "--strict").exit_code == 0

    report.unlink()
    rebuilt = setup.run("ingest", "report")
    assert rebuilt.exit_code == 0
    assert report.is_file()


def test_a_failing_server_is_reported(setup: Setup, monkeypatch: pytest.MonkeyPatch) -> None:
    serve(monkeypatch, b"", status=404)
    result = setup.run("ingest", "download", "pcb-defect")
    assert result.exit_code == 1
    assert "HTTP 404" in result.output


def test_a_download_that_does_not_match_the_record_is_refused(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    serve(monkeypatch, setup.payload + b"tampered")
    result = setup.run("ingest", "download", "pcb-defect")
    assert result.exit_code == 1
    assert "does not match the repository record" in result.output
    assert not (setup.data / "raw" / "pcb-defect" / "PCB_Defect.zip").exists()


def test_the_data_directory_must_be_outside_the_repository(setup: Setup) -> None:
    result = setup.run("ingest", "download", "pcb-defect", data=setup.repo.root / "data")
    assert result.exit_code == 1
    assert "inside the repository" in result.output


def test_the_data_directory_must_be_configured(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENINSPECT_DATA_DIR", raising=False)
    result = setup.repo.cli("ingest", "download", "pcb-defect")
    assert result.exit_code == 1
    assert "OPENINSPECT_DATA_DIR is not set" in result.output


def test_the_data_directory_can_come_from_the_dotenv_file(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENINSPECT_DATA_DIR", raising=False)
    (setup.repo.root / ".env").write_text(f"OPENINSPECT_DATA_DIR={setup.data}\n", encoding="utf-8")
    serve(monkeypatch, setup.payload)
    assert setup.repo.cli("ingest", "download", "pcb-defect").exit_code == 0


def test_only_accepted_sources_can_be_selected(setup: Setup) -> None:
    setup.repo.write_manifest(pending_manifest("demo-pending"))
    refused = setup.run("ingest", "download", "demo-pending")
    assert refused.exit_code == 1
    assert "only accepted sources" in refused.output
    unknown = setup.run("ingest", "download", "nope")
    assert unknown.exit_code == 1
    assert "no source with slug" in unknown.output
    nothing = setup.run("ingest", "download")
    assert nothing.exit_code == 1
    assert "name at least one source" in nothing.output


def test_extract_and_run_need_the_download_first(setup: Setup) -> None:
    extract = setup.run("ingest", "extract", "pcb-defect")
    assert extract.exit_code == 1
    assert "not downloaded yet" in extract.output
    run = setup.run("ingest", "run", "pcb-defect")
    assert run.exit_code == 1
    assert "ingest download pcb-defect" in run.output


def test_inspect_needs_an_extracted_source(setup: Setup) -> None:
    result = setup.run("ingest", "inspect", "pcb-defect")
    assert result.exit_code == 1
    assert "not extracted yet" in result.output
    assert setup.run("ingest", "inspect", "nope").exit_code == 1


def test_report_needs_a_run_first(setup: Setup) -> None:
    result = setup.run("ingest", "report")
    assert result.exit_code == 1
    assert "no ingest report found" in result.output


def test_a_full_disk_stops_the_download(setup: Setup, monkeypatch: pytest.MonkeyPatch) -> None:
    def full(_path: Path, _needed: int) -> None:
        raise DataDirError("not enough free space on the drive")

    monkeypatch.setattr("openinspect.cli.ingest.ensure_free_space", full)
    result = setup.run("ingest", "download", "pcb-defect")
    assert result.exit_code == 1
    assert "not enough free space" in result.output


def test_a_broken_registry_stops_ingestion(setup: Setup) -> None:
    (setup.repo.sources / "broken.yaml").write_text("a: [1", encoding="utf-8")
    result = setup.run("ingest", "download", "pcb-defect")
    assert result.exit_code == 1
    assert "the source registry has errors" in result.output
