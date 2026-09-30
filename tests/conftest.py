from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner, Result

from openinspect.cli import app
from tests.factories import EVIDENCE_BYTES, EVIDENCE_REL, EVIDENCE_SHA, LICENCES_YAML


@dataclass
class Repo:
    """A throw-away repository: licence config, manifests directory and one evidence file."""

    root: Path

    @property
    def sources(self) -> Path:
        return self.root / "manifests" / "sources"

    def write_manifest(self, data: dict[str, Any], name: str | None = None) -> Path:
        path = self.sources / f"{name or data['slug']}.yaml"
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        return path

    def write_file(self, name: str, data: dict[str, Any]) -> Path:
        """A manifest file outside the registry, to import with ``--from-file``."""
        path = self.root / name
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        return path

    def cli(self, *args: str) -> Result:
        return CliRunner().invoke(app, [*args, "--repo-root", str(self.root)])


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "licences.yaml").write_text(LICENCES_YAML, encoding="utf-8")
    (tmp_path / "manifests" / "sources").mkdir(parents=True)
    evidence = tmp_path / EVIDENCE_REL
    evidence.parent.mkdir(parents=True)
    evidence.write_bytes(EVIDENCE_BYTES)
    index = tmp_path / "manifests" / "evidence" / "SHA256SUMS.txt"
    index.write_text(f"{EVIDENCE_SHA}  demo-source/record.json\n", encoding="ascii")
    return Repo(tmp_path)
