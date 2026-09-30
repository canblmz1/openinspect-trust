"""The ingest CLI when things are not perfect: repeated runs, tampered manifests, bad archives."""

from __future__ import annotations

import hashlib
import json
import zipfile
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest

from openinspect.provenance.registry import load_registry
from tests.conftest import Repo
from tests.factories import accepted_manifest, pending_manifest
from tests.ingest_fixtures import build_pcb_defect, build_pcb_ind, zip_tree

Builder = Callable[[Path], None]


class Sources:
    """Registers synthetic sources and serves their archives from memory."""

    def __init__(self, repo: Repo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.repo = repo
        self.tmp_path = tmp_path
        self.data = tmp_path / "data"
        self.payloads: dict[str, bytes] = {}
        client = httpx.Client(transport=httpx.MockTransport(self._handle), follow_redirects=True)
        monkeypatch.setattr("openinspect.cli.ingest._http_client", lambda: client)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        payload = self.payloads.get(str(request.url))
        return httpx.Response(200, content=payload) if payload is not None else httpx.Response(404)

    def add(
        self,
        slug: str,
        builder: Builder | None = None,
        *,
        payload: bytes | None = None,
        junk: bool = False,
        acquisition: dict[str, Any] | None = None,
        files: int = 1,
    ) -> bytes:
        if payload is None:
            assert builder is not None
            tree = self.tmp_path / "work" / slug
            builder(tree)
            archive = self.tmp_path / "work" / f"{slug}.zip"
            zip_tree(tree, archive)
            if junk:
                with zipfile.ZipFile(archive, "a") as zf:
                    zf.writestr("__MACOSX/._junk", b"x")
            payload = archive.read_bytes()
        url = f"https://example.org/{slug}.zip"
        self.payloads[url] = payload
        spec = {
            "url": url,
            "filename": f"{slug}.zip",
            "bytes": len(payload),
            "record_checksum": {"algo": "sha256", "value": hashlib.sha256(payload).hexdigest()},
        }
        manifest = accepted_manifest(slug)
        manifest["acquisition"] = {
            "download_method": "http",
            "download_files": [spec] * files,
            "download_date": None,
            "archive_sha256": None,
            "sha256_manifest": None,
        }
        manifest["acquisition"].update(acquisition or {})
        self.repo.write_manifest(manifest)
        return payload

    def cli(self, *args: str) -> Any:
        return self.repo.cli(*args, "--data-dir", str(self.data))


@pytest.fixture
def sources(repo: Repo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Sources:
    return Sources(repo, tmp_path, monkeypatch)


def recorded(repo: Repo, slug: str) -> Any:
    item = load_registry(repo.root).get(slug)
    assert item is not None
    return item.manifest.acquisition


def test_the_first_download_date_survives_a_later_run(sources: Sources) -> None:
    sources.add("pcb-defect", build_pcb_defect, acquisition={"download_date": date(2020, 1, 1)})
    assert sources.cli("ingest", "download", "pcb-defect").exit_code == 0
    again = sources.cli("ingest", "download", "pcb-defect")
    assert again.exit_code == 0
    acquisition = recorded(sources.repo, "pcb-defect")
    assert acquisition.download_date == date(2020, 1, 1)
    assert acquisition.archive_sha256 is not None


def test_a_different_archive_hash_in_the_manifest_is_an_integrity_alarm(sources: Sources) -> None:
    sources.add(
        "pcb-defect", build_pcb_defect, acquisition={"archive_sha256": {"pcb-defect.zip": "0" * 64}}
    )
    result = sources.cli("ingest", "download", "pcb-defect")
    assert result.exit_code == 1
    assert "already set" in result.output


def test_run_refuses_to_replace_a_different_report_path(sources: Sources) -> None:
    sources.add(
        "pcb-defect",
        build_pcb_defect,
        acquisition={"sha256_manifest": "manifests/ingest/elsewhere/report.json"},
    )
    assert sources.cli("ingest", "download", "pcb-defect").exit_code == 0
    result = sources.cli("ingest", "run", "pcb-defect")
    assert result.exit_code == 1
    assert "already set" in result.output


def test_extract_reports_an_archive_that_is_not_a_zip(sources: Sources) -> None:
    sources.add("pcb-defect", payload=b"this is not a zip archive")
    assert sources.cli("ingest", "download", "pcb-defect").exit_code == 0
    result = sources.cli("ingest", "extract", "pcb-defect")
    assert result.exit_code == 1
    assert "not a valid zip" in result.output


def test_extract_prints_what_needed_special_handling(sources: Sources) -> None:
    sources.add("pcb-defect", build_pcb_defect, junk=True)
    sources.cli("ingest", "download", "pcb-defect")
    result = sources.cli("ingest", "extract", "pcb-defect")
    assert result.exit_code == 0
    assert "1 anomalies" in result.output
    assert "anomaly: archiver junk" in result.output


def test_all_needs_at_least_one_accepted_source(sources: Sources) -> None:
    sources.repo.write_manifest(pending_manifest("demo-pending"))
    result = sources.cli("ingest", "download", "--all")
    assert result.exit_code == 1
    assert "no accepted source selected" in result.output


def test_a_manifest_with_two_archives_cannot_be_extracted(sources: Sources) -> None:
    sources.add("pcb-defect", build_pcb_defect, files=2)
    sources.cli("ingest", "download", "pcb-defect")
    result = sources.cli("ingest", "extract", "pcb-defect")
    assert result.exit_code == 1
    assert "exactly one archive" in result.output


def test_two_sources_are_compared_for_shared_images(sources: Sources) -> None:
    sources.add("pcb-defect", build_pcb_defect)
    sources.add("pcb-ind", build_pcb_ind)
    assert sources.cli("ingest", "download", "--all").exit_code == 0
    result = sources.cli("ingest", "run", "--all")
    assert result.exit_code == 0, result.output
    cross = json.loads(
        (sources.repo.root / "manifests" / "ingest" / "cross_source.json").read_text(
            encoding="utf-8"
        )
    )
    assert cross["sources"] == ["pcb-defect", "pcb-ind"]
    assert cross["shared_sha256"] == 0
    text = (sources.repo.root / "reports" / "m2-ingest-report.md").read_text(encoding="utf-8")
    assert "Cross-source exact duplicates" in text
    assert "`pcb-defect`" in text
    assert "`pcb-ind`" in text
