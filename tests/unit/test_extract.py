from __future__ import annotations

import hashlib
import sys
import zipfile
from pathlib import Path

import pytest

from openinspect.ingest.extract import ExtractError, extract_zip, format_sha256_list


def make_zip(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path


def test_extraction_writes_the_files_and_their_hashes(tmp_path: Path) -> None:
    archive = make_zip(tmp_path / "a.zip", {"b/x.txt": b"hello", "a.txt": b"world", "empty/": b""})
    result = extract_zip(archive, tmp_path / "out")
    assert (tmp_path / "out" / "b" / "x.txt").read_bytes() == b"hello"
    assert (tmp_path / "out" / "empty").is_dir()
    assert [f.path for f in result.files] == ["a.txt", "b/x.txt"]
    assert result.files[0].sha256 == hashlib.sha256(b"world").hexdigest()
    assert result.files[0].size == 5
    assert result.bytes == 10
    assert result.anomalies == ()
    assert not (tmp_path / "out.partial").exists()


def test_the_hash_list_is_sha256sum_format_sorted_with_lf(tmp_path: Path) -> None:
    result = extract_zip(
        make_zip(tmp_path / "a.zip", {"z.txt": b"1", "B.txt": b"2"}), tmp_path / "out"
    )
    text = format_sha256_list(result.files)
    lines = text.splitlines()
    assert [line.split("  ", 1)[1] for line in lines] == ["B.txt", "z.txt"]
    assert "\r" not in text
    assert text.endswith("\n")


def test_a_file_that_is_not_a_zip_is_refused(tmp_path: Path) -> None:
    bad = tmp_path / "a.zip"
    bad.write_bytes(b"this is not a zip")
    with pytest.raises(ExtractError, match="not a zip"):
        extract_zip(bad, tmp_path / "out")


def test_an_existing_target_is_refused(tmp_path: Path) -> None:
    (tmp_path / "out").mkdir()
    with pytest.raises(ExtractError, match="already exists"):
        extract_zip(make_zip(tmp_path / "a.zip", {"a.txt": b"x"}), tmp_path / "out")


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("../evil.txt", "path traversal"),
        ("a/../../evil.txt", "path traversal"),
        ("/etc/passwd", "absolute path"),
        ("C:/windows/x.txt", "absolute path"),
        ("bad\x01name.txt", "control character"),
        ("trailing.", "dot or a space"),
        ("nul.txt", "reserved device name"),
        ("dir/COM1", "reserved device name"),
    ],
)
def test_unsafe_member_names_are_refused_and_nothing_is_left_behind(
    tmp_path: Path, name: str, message: str
) -> None:
    archive = make_zip(tmp_path / "a.zip", {"fine.txt": b"x", name: b"boom"})
    with pytest.raises(ExtractError, match=message):
        extract_zip(archive, tmp_path / "out")
    assert not (tmp_path / "out").exists()
    assert not (tmp_path / "out.partial").exists()
    assert not (tmp_path.parent / "evil.txt").exists()


def test_names_that_differ_only_by_case_collide(tmp_path: Path) -> None:
    archive = make_zip(tmp_path / "a.zip", {"Data/a.jpg": b"1", "data/A.JPG": b"2"})
    with pytest.raises(ExtractError, match="collide"):
        extract_zip(archive, tmp_path / "out")


def test_a_member_named_twice_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "a.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("a.txt", b"1")
        with pytest.warns(UserWarning, match="Duplicate name"):
            zf.writestr("a.txt", b"2")
    with pytest.raises(ExtractError, match="collide"):
        extract_zip(path, tmp_path / "out")


def test_backslashes_in_member_names_become_directories(tmp_path: Path) -> None:
    result = extract_zip(make_zip(tmp_path / "a.zip", {"dir\\file.txt": b"x"}), tmp_path / "out")
    assert (tmp_path / "out" / "dir" / "file.txt").read_bytes() == b"x"
    assert [f.path for f in result.files] == ["dir/file.txt"]


@pytest.mark.skipif(
    sys.platform == "win32", reason="zipfile rewrites backslashes itself on Windows"
)
def test_backslashes_are_reported_where_zipfile_keeps_them(tmp_path: Path) -> None:
    result = extract_zip(make_zip(tmp_path / "a.zip", {"dir\\file.txt": b"x"}), tmp_path / "out")
    assert any("backslash" in a for a in result.anomalies)


def test_symbolic_links_are_skipped_and_reported(tmp_path: Path) -> None:
    path = tmp_path / "a.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("real.txt", b"data")
        link = zipfile.ZipInfo("link.txt")
        link.external_attr = 0o120777 << 16
        zf.writestr(link, b"real.txt")
    result = extract_zip(path, tmp_path / "out")
    assert [f.path for f in result.files] == ["real.txt"]
    assert not (tmp_path / "out" / "link.txt").exists()
    assert any("symbolic link" in a for a in result.anomalies)


def test_archiver_junk_is_reported_but_extracted(tmp_path: Path) -> None:
    result = extract_zip(
        make_zip(tmp_path / "a.zip", {"__MACOSX/._x": b"1", "x": b"2"}), tmp_path / "out"
    )
    assert any("junk" in a for a in result.anomalies)
    assert len(result.files) == 2


def test_limits_protect_against_huge_archives(tmp_path: Path) -> None:
    archive = make_zip(tmp_path / "a.zip", {"a": b"1", "b": b"2", "c": b"3"})
    with pytest.raises(ExtractError, match="members exceed"):
        extract_zip(archive, tmp_path / "o1", max_members=2)
    with pytest.raises(ExtractError, match="uncompressed bytes exceed"):
        extract_zip(archive, tmp_path / "o2", max_bytes=2)


def test_a_corrupt_member_is_detected_by_its_crc(tmp_path: Path) -> None:
    payload = b"payload-" * 40
    path = tmp_path / "a.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("a.bin", payload)
    raw = bytearray(path.read_bytes())
    at = raw.index(payload)
    raw[at + 5] ^= 0xFF
    path.write_bytes(bytes(raw))
    with pytest.raises(ExtractError, match="corrupt archive"):
        extract_zip(path, tmp_path / "out")
    assert not (tmp_path / "out").exists()
    assert not (tmp_path / "out.partial").exists()


def test_a_stale_partial_directory_is_cleaned_up(tmp_path: Path) -> None:
    stale = tmp_path / "out.partial"
    stale.mkdir()
    (stale / "old.txt").write_text("old", encoding="utf-8")
    extract_zip(make_zip(tmp_path / "a.zip", {"new.txt": b"n"}), tmp_path / "out")
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["new.txt"]
