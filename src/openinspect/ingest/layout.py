"""Where the files of one source live under the data directory."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SourceDirs:
    raw: Path  # downloaded archives, never edited
    extracted: Path  # unpacked files, never edited
    records: Path  # derived, regenerable: image and annotation records, extraction marker


def source_dirs(data_dir: Path, slug: str) -> SourceDirs:
    return SourceDirs(
        raw=data_dir / "raw" / slug,
        extracted=data_dir / "extracted" / slug,
        records=data_dir / "records" / slug,
    )
