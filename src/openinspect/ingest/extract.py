"""Safe extraction of source archives, with a SHA-256 for every extracted file.

Archives come from third parties, so nothing in them is trusted: absolute paths, ``..`` components,
Windows reserved names, case-only name clashes, symbolic links and oversized archives are refused or
skipped. The archive is unpacked into ``<target>.partial`` and renamed only when everything worked.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

GIB = 1 << 30
CHUNK = 1 << 20
_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_CONTROL = re.compile(r"[\x00-\x1f]")
_DRIVE = re.compile(r"^[A-Za-z]:")
_JUNK = {"__MACOSX", ".DS_Store", "Thumbs.db", "desktop.ini"}


class ExtractError(Exception):
    """The archive is corrupt or unsafe to unpack."""


@dataclass(frozen=True)
class ExtractedFile:
    path: str  # POSIX path relative to the extraction root
    size: int
    sha256: str


@dataclass(frozen=True)
class ExtractResult:
    files: tuple[ExtractedFile, ...]
    anomalies: tuple[str, ...]
    members: int
    bytes: int


def _safe_path(name: str, anomalies: list[str]) -> PurePosixPath:
    if "\\" in name:
        anomalies.append(f"backslash in member name {name!r}: treated as a separator")
        name = name.replace("\\", "/")
    if _CONTROL.search(name):
        raise ExtractError(f"control character in member name {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or _DRIVE.match(name):
        raise ExtractError(f"absolute path in archive: {name!r}")
    if ".." in path.parts:
        raise ExtractError(f"path traversal in archive: {name!r}")
    for part in path.parts:
        if part != part.rstrip(" ."):
            raise ExtractError(f"name ends with a dot or a space (invalid on Windows): {name!r}")
        if part.split(".")[0].upper() in _RESERVED:
            raise ExtractError(f"Windows reserved device name in archive: {name!r}")
    if not path.parts:
        raise ExtractError(f"empty member name {name!r}")
    return path


def extract_zip(
    archive: Path,
    target: Path,
    *,
    max_members: int = 500_000,
    max_bytes: int = 20 * GIB,
) -> ExtractResult:
    """Unpack ``archive`` into ``target`` (which must not exist yet) and hash every file."""
    if not zipfile.is_zipfile(archive):
        raise ExtractError(f"{archive.name} is not a zip archive")
    if target.exists():
        raise ExtractError(f"{target} already exists")
    partial = target.with_name(target.name + ".partial")
    if partial.exists():
        shutil.rmtree(partial)
    partial.mkdir(parents=True)
    anomalies: list[str] = []
    files: list[ExtractedFile] = []
    try:
        with zipfile.ZipFile(archive) as zf:
            infos = zf.infolist()
            if len(infos) > max_members:
                raise ExtractError(f"{len(infos)} members exceed the limit of {max_members}")
            declared = sum(info.file_size for info in infos)
            if declared > max_bytes:
                raise ExtractError(f"{declared} uncompressed bytes exceed the limit of {max_bytes}")
            seen: dict[str, str] = {}
            root = partial.resolve()
            for info in infos:
                rel = _safe_path(info.filename, anomalies)
                if info.is_dir():
                    (partial / rel).mkdir(parents=True, exist_ok=True)
                    continue
                key = rel.as_posix().lower()
                if key in seen:
                    raise ExtractError(
                        f"members {seen[key]!r} and {rel.as_posix()!r} collide "
                        "(same name, case aside)"
                    )
                seen[key] = rel.as_posix()
                if stat.S_ISLNK(info.external_attr >> 16):
                    anomalies.append(f"symbolic link skipped: {rel.as_posix()}")
                    continue
                if any(part in _JUNK for part in rel.parts):
                    anomalies.append(f"archiver junk: {rel.as_posix()}")
                destination = partial / rel
                if not destination.resolve().is_relative_to(root):
                    raise ExtractError(  # pragma: no cover - defensive, names are checked above
                        f"member escapes the extraction root: {rel.as_posix()!r}"
                    )
                destination.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                size = 0
                with zf.open(info) as source, destination.open("wb") as out:
                    while block := source.read(CHUNK):
                        digest.update(block)
                        out.write(block)
                        size += len(block)
                if size != info.file_size:
                    raise ExtractError(  # pragma: no cover - zipfile checks sizes itself
                        f"{rel.as_posix()}: {size} bytes read, {info.file_size} declared"
                    )
                files.append(ExtractedFile(rel.as_posix(), size, digest.hexdigest()))
        partial.rename(target)
    except zipfile.BadZipFile as exc:
        shutil.rmtree(partial, ignore_errors=True)
        raise ExtractError(f"corrupt archive {archive.name}: {exc}") from exc
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    files.sort(key=lambda f: f.path)
    return ExtractResult(
        files=tuple(files),
        anomalies=tuple(anomalies),
        members=len(infos),
        bytes=sum(f.size for f in files),
    )


def format_sha256_list(files: tuple[ExtractedFile, ...] | list[ExtractedFile]) -> str:
    """``sha256sum`` format, sorted byte-wise by path, LF line endings."""
    return "".join(f"{f.sha256}  {f.path}\n" for f in sorted(files, key=lambda f: f.path))
