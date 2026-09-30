from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from openinspect.ingest.download import DownloadError, download, hash_file
from openinspect.provenance.schema import Checksum, DownloadFile

DATA = bytes(range(256)) * 8  # 2048 bytes
URL = "https://example.org/archive.zip"


def spec(
    *, size: int | None = len(DATA), algo: str | None = "md5", value: str | None = None
) -> DownloadFile:
    checksum = None
    if algo is not None:
        digest = value or hashlib.new(algo, DATA, usedforsecurity=False).hexdigest()
        checksum = Checksum(algo=algo, value=digest)  # type: ignore[arg-type]
    return DownloadFile(url=URL, filename="archive.zip", bytes=size, record_checksum=checksum)


def client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def serve(data: bytes = DATA) -> Callable[[httpx.Request], httpx.Response]:
    return lambda request: httpx.Response(200, content=data, headers={"etag": '"abc"'})


def no_sleep(_seconds: float) -> None:
    return None


def test_a_matching_download_is_kept_and_described(tmp_path: Path) -> None:
    record = download(spec(), tmp_path, client=client(serve()), sleep=no_sleep)
    assert (tmp_path / "archive.zip").read_bytes() == DATA
    assert not (tmp_path / "archive.zip.part").exists()
    assert record.bytes == len(DATA)
    assert record.size_ok is True
    assert record.checksum_ok is True
    assert record.checksum_algo == "md5"
    assert record.sha256 == hashlib.sha256(DATA).hexdigest()
    assert record.skipped is False
    assert record.http_status == 200
    assert record.etag == '"abc"'


def test_sha256_records_are_verified_too(tmp_path: Path) -> None:
    record = download(spec(algo="sha256"), tmp_path, client=client(serve()), sleep=no_sleep)
    assert record.checksum_ok is True


def test_a_download_without_expectations_is_still_hashed(tmp_path: Path) -> None:
    record = download(spec(size=None, algo=None), tmp_path, client=client(serve()), sleep=no_sleep)
    assert record.size_ok is None
    assert record.checksum_ok is None
    assert record.sha256 == hashlib.sha256(DATA).hexdigest()


def test_a_file_that_is_already_there_and_verifies_is_not_downloaded_again(tmp_path: Path) -> None:
    (tmp_path / "archive.zip").write_bytes(DATA)

    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("the network must not be touched")

    record = download(spec(), tmp_path, client=client(handler), sleep=no_sleep)
    assert record.skipped is True


def test_a_file_that_does_not_verify_is_replaced(tmp_path: Path) -> None:
    (tmp_path / "archive.zip").write_bytes(b"corrupt")
    record = download(spec(), tmp_path, client=client(serve()), sleep=no_sleep)
    assert record.skipped is False
    assert (tmp_path / "archive.zip").read_bytes() == DATA


def test_a_size_mismatch_is_an_error_and_nothing_is_kept(tmp_path: Path) -> None:
    with pytest.raises(DownloadError, match="size differs"):
        download(
            spec(size=len(DATA) + 1, algo=None), tmp_path, client=client(serve()), sleep=no_sleep
        )
    assert list(tmp_path.iterdir()) == []


def test_a_checksum_mismatch_is_an_error_and_nothing_is_kept(tmp_path: Path) -> None:
    with pytest.raises(DownloadError, match="md5 differs"):
        download(spec(value="0" * 32), tmp_path, client=client(serve()), sleep=no_sleep)
    assert list(tmp_path.iterdir()) == []


def test_a_server_error_is_retried_with_backoff(tmp_path: Path) -> None:
    calls: list[int] = []
    waits: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, content=DATA)

    record = download(spec(), tmp_path, client=client(handler), sleep=waits.append, backoff=2.0)
    assert record.checksum_ok is True
    assert len(calls) == 3
    assert waits == [1.0, 2.0]


def test_a_dropped_connection_is_retried(tmp_path: Path) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(200, content=DATA)

    assert download(spec(), tmp_path, client=client(handler), sleep=no_sleep).checksum_ok is True


def test_giving_up_after_the_retries_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(DownloadError, match="giving up after 3 attempts"):
        download(
            spec(),
            tmp_path,
            client=client(lambda _r: httpx.Response(500)),
            retries=2,
            sleep=no_sleep,
        )


def test_a_client_error_is_not_retried(tmp_path: Path) -> None:
    calls: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(404)

    with pytest.raises(DownloadError, match="HTTP 404"):
        download(spec(), tmp_path, client=client(handler), sleep=no_sleep)
    assert len(calls) == 1


def test_a_partial_file_is_resumed_when_the_server_honours_range(tmp_path: Path) -> None:
    (tmp_path / "archive.zip.part").write_bytes(DATA[:700])
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("range"))
        return httpx.Response(206, content=DATA[700:])

    record = download(spec(), tmp_path, client=client(handler), sleep=no_sleep)
    assert seen == ["bytes=700-"]
    assert record.resumed is True
    assert record.checksum_ok is True


def test_a_server_that_ignores_range_restarts_from_the_top(tmp_path: Path) -> None:
    (tmp_path / "archive.zip.part").write_bytes(b"stale bytes")
    record = download(spec(), tmp_path, client=client(serve()), sleep=no_sleep)
    assert record.resumed is False
    assert (tmp_path / "archive.zip").read_bytes() == DATA


def test_range_not_satisfiable_restarts(tmp_path: Path) -> None:
    (tmp_path / "archive.zip.part").write_bytes(b"x" * 5000)  # longer than the real file
    calls: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(416) if len(calls) == 1 else httpx.Response(200, content=DATA)

    assert download(spec(), tmp_path, client=client(handler), sleep=no_sleep).checksum_ok is True


def test_progress_is_reported(tmp_path: Path) -> None:
    seen: list[tuple[int, int | None]] = []
    download(
        spec(),
        tmp_path,
        client=client(
            lambda _r: httpx.Response(200, content=DATA, headers={"content-length": str(len(DATA))})
        ),
        sleep=no_sleep,
        progress=lambda done, total: seen.append((done, total)),
    )
    assert seen
    assert seen[-1] == (len(DATA), len(DATA))


def test_a_manifest_without_a_url_cannot_be_downloaded(tmp_path: Path) -> None:
    no_url = DownloadFile(url=None, filename="archive.zip")
    with pytest.raises(DownloadError, match="no download URL"):
        download(no_url, tmp_path, client=client(serve()), sleep=no_sleep)


def test_hash_file_returns_every_requested_digest(tmp_path: Path) -> None:
    path = tmp_path / "f.bin"
    path.write_bytes(DATA)
    digests = hash_file(path, ["sha256", "md5", "sha1"])
    assert digests["sha256"] == hashlib.sha256(DATA).hexdigest()
    assert digests["md5"] == hashlib.md5(DATA, usedforsecurity=False).hexdigest()
    assert set(digests) == {"sha256", "md5", "sha1"}
