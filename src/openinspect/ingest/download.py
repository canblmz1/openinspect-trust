"""Reproducible, verified downloads of the archives named in a source manifest.

A download is accepted only when its size and its checksum match what the repository record says.
A file that does not match is never kept.
"""

from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

from openinspect import __version__
from openinspect.provenance.schema import DownloadFile

USER_AGENT = f"openinspect-trust/{__version__} (+https://github.com/canblmz1/openinspect-trust)"
CHUNK = 1 << 20
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})

Progress = Callable[[int, int | None], None]


class DownloadError(Exception):
    """The download failed or did not match the repository record."""


@dataclass(frozen=True)
class DownloadRecord:
    """What was downloaded and how it compares with the upstream record."""

    filename: str
    url: str
    bytes: int
    sha256: str
    md5: str
    size_expected: int | None
    size_ok: bool | None
    checksum_algo: str | None
    checksum_expected: str | None
    checksum_ok: bool | None
    skipped: bool  # the file was already present and verified
    resumed: bool
    http_status: int | None
    etag: str | None
    last_modified: str | None
    downloaded_at: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class Verification:
    size_expected: int | None
    size_ok: bool | None
    algo: str | None
    expected: str | None
    checksum_ok: bool | None

    @property
    def passed(self) -> bool:
        return self.size_ok is not False and self.checksum_ok is not False

    def describe(self) -> str:
        parts = []
        if self.size_ok is False:
            parts.append(f"size differs from the record ({self.size_expected} bytes expected)")
        if self.checksum_ok is False:
            parts.append(f"{self.algo} differs from the record ({self.expected} expected)")
        return "; ".join(parts) or "ok"


def hash_file(path: Path, algos: Iterable[str] = ("sha256", "md5")) -> dict[str, str]:
    """Digests of a file, computed in a single pass."""
    hashers = {name: hashlib.new(name, usedforsecurity=False) for name in algos}
    with path.open("rb") as handle:
        while block := handle.read(CHUNK):
            for hasher in hashers.values():
                hasher.update(block)
    return {name: hasher.hexdigest() for name, hasher in hashers.items()}


def verify_file(path: Path, spec: DownloadFile) -> tuple[Verification, dict[str, str], int]:
    """Compare a file with the size and checksum in the manifest."""
    checksum = spec.record_checksum
    algos = {"sha256", "md5"} | ({checksum.algo} if checksum else set())
    digests = hash_file(path, sorted(algos))
    size = path.stat().st_size
    verification = Verification(
        size_expected=spec.bytes,
        size_ok=None if spec.bytes is None else size == spec.bytes,
        algo=checksum.algo if checksum else None,
        expected=checksum.value if checksum else None,
        checksum_ok=None if checksum is None else digests[checksum.algo] == checksum.value,
    )
    return verification, digests, size


def _record(
    spec: DownloadFile,
    path: Path,
    *,
    skipped: bool,
    resumed: bool,
    status: int | None,
    etag: str | None,
    last_modified: str | None,
) -> DownloadRecord:
    verification, digests, size = verify_file(path, spec)
    return DownloadRecord(
        filename=spec.filename,
        url=spec.url or "",
        bytes=size,
        sha256=digests["sha256"],
        md5=digests["md5"],
        size_expected=verification.size_expected,
        size_ok=verification.size_ok,
        checksum_algo=verification.algo,
        checksum_expected=verification.expected,
        checksum_ok=verification.checksum_ok,
        skipped=skipped,
        resumed=resumed,
        http_status=status,
        etag=etag,
        last_modified=last_modified,
        downloaded_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )


def _stream_to_part(
    http: httpx.Client,
    url: str,
    part: Path,
    progress: Progress | None,
) -> tuple[int, str | None, str | None, bool]:
    """One attempt. Returns ``(status, etag, last_modified, resumed)`` or raises for a retry."""
    offset = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    with http.stream("GET", url, headers=headers) as response:
        if response.status_code == 416:  # the partial file does not fit the remote file
            part.unlink(missing_ok=True)
            raise _RetryError("range not satisfiable, restarting")
        if response.status_code in RETRY_STATUS:
            raise _RetryError(f"HTTP {response.status_code}")
        if response.status_code not in (200, 206):
            raise DownloadError(f"{url}: HTTP {response.status_code}")
        resumed = response.status_code == 206 and offset > 0
        if not resumed:
            offset = 0  # the server ignored the Range header: start from the top
        declared = response.headers.get("content-length")
        total = offset + int(declared) if declared and declared.isdigit() else None
        written = offset
        with part.open("ab" if resumed else "wb") as out:
            for block in response.iter_bytes(CHUNK):
                out.write(block)
                written += len(block)
                if progress is not None:
                    progress(written, total)
        if total is not None and written != total:
            raise _RetryError(f"connection closed after {written} of {total} bytes")
        return (
            response.status_code,
            response.headers.get("etag"),
            response.headers.get("last-modified"),
            resumed,
        )


class _RetryError(Exception):
    """Internal: this attempt failed in a way that is worth repeating."""


def download(
    spec: DownloadFile,
    dest_dir: Path,
    *,
    client: httpx.Client | None = None,
    retries: int = 3,
    backoff: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
    progress: Progress | None = None,
) -> DownloadRecord:
    """Download ``spec`` into ``dest_dir`` and verify it against the manifest.

    An existing file that verifies is kept (``skipped``); one that does not is deleted. A partial
    ``.part`` file is resumed when the server honours ``Range``.
    """
    if spec.url is None:
        raise DownloadError(f"{spec.filename}: the manifest has no download URL")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / spec.filename
    if dest.is_file():
        verification, _, _ = verify_file(dest, spec)
        if verification.passed:
            return _record(
                spec, dest, skipped=True, resumed=False, status=None, etag=None, last_modified=None
            )
        dest.unlink()  # a file that does not match upstream is never kept
    part = dest.with_name(dest.name + ".part")
    owns_client = client is None
    http = client or httpx.Client(
        timeout=httpx.Timeout(30.0, read=120.0),
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )
    outcome: tuple[int, str | None, str | None, bool] | None = None
    try:
        for attempt in range(1, retries + 2):
            try:
                outcome = _stream_to_part(http, spec.url, part, progress)
                break
            except (_RetryError, httpx.TransportError) as exc:
                if attempt > retries:
                    raise DownloadError(
                        f"{spec.filename}: giving up after {attempt} attempts ({exc})"
                    ) from exc
                sleep(backoff ** (attempt - 1))
    finally:
        if owns_client:
            http.close()
    if outcome is None:  # pragma: no cover - the loop either breaks or raises
        raise DownloadError(f"{spec.filename}: no response")
    status, etag, last_modified, resumed = outcome
    verification, _, _ = verify_file(part, spec)
    if not verification.passed:
        part.unlink(missing_ok=True)
        raise DownloadError(
            f"{spec.filename}: does not match the repository record: {verification.describe()}"
        )
    os.replace(part, dest)
    return _record(
        spec,
        dest,
        skipped=False,
        resumed=resumed,
        status=status,
        etag=etag,
        last_modified=last_modified,
    )
