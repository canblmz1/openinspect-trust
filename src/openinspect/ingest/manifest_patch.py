"""Fill the ``acquisition`` fields of a manifest in place, keeping its comments and layout.

Manifests are curated documents, so they are edited as text (one line per field) instead of being
re-serialised. The patched text is parsed again and only written when it is still a valid manifest.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import date
from pathlib import Path

from openinspect.provenance.registry import parse_manifest_text


class ManifestPatchError(Exception):
    """The manifest could not be patched safely."""


def _block_bounds(lines: list[str], block: str) -> tuple[int, int]:
    start = next((i for i, ln in enumerate(lines) if ln.rstrip() == f"{block}:"), None)
    if start is None:
        raise ManifestPatchError(f"no top-level '{block}:' block")
    end = start + 1
    while end < len(lines) and (not lines[end].strip() or lines[end].startswith((" ", "#"))):
        end += 1
    return start, end


def _set_field(lines: list[str], start: int, end: int, key: str, rendered: str) -> bool:
    pattern = re.compile(rf"^(\s{{2}}{re.escape(key)}:)\s*(.*?)(\s+#.*)?$")
    for i in range(start + 1, end):
        match = pattern.match(lines[i])
        if match is None:
            continue
        current = match.group(2).strip()
        if current == rendered:
            return False
        if current not in ("null", "~", ""):
            raise ManifestPatchError(f"acquisition.{key} is already set to {current!r}")
        if current == "" and i + 1 < end and lines[i + 1].startswith("    "):
            raise ManifestPatchError(f"acquisition.{key} is already set (as a YAML block)")
        lines[i] = f"{match.group(1)} {rendered}{match.group(3) or ''}"
        return True
    raise ManifestPatchError(f"acquisition.{key} not found")


def set_acquisition_fields(
    path: Path,
    *,
    download_date: date | None = None,
    archive_sha256: Mapping[str, str] | None = None,
    sha256_manifest: str | None = None,
) -> bool:
    """Set the given ``acquisition`` fields (only where they are still null). Returns ``True`` if changed."""
    original = path.read_text(encoding="utf-8")
    lines = original.split("\n")
    start, end = _block_bounds(lines, "acquisition")
    changed = False
    if download_date is not None:
        changed |= _set_field(lines, start, end, "download_date", download_date.isoformat())
    if archive_sha256 is not None:
        changed |= _set_field(
            lines, start, end, "archive_sha256", json.dumps(dict(sorted(archive_sha256.items())))
        )
    if sha256_manifest is not None:
        changed |= _set_field(lines, start, end, "sha256_manifest", json.dumps(sha256_manifest))
    if not changed:
        return False
    patched = "\n".join(lines)
    manifest, issues = parse_manifest_text(patched, path.as_posix())
    if manifest is None:
        raise ManifestPatchError(
            "the patched manifest is invalid: " + "; ".join(i.message for i in issues)
        )
    path.write_bytes(patched.encode("utf-8"))
    return True
