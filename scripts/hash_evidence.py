"""Regenerate manifests/evidence/SHA256SUMS.txt.

The file uses the ``sha256sum`` format (``<hash>  <path>``, two spaces, LF line endings), paths are
relative to ``manifests/evidence/`` and sorted byte-wise so the output does not depend on the OS.

    python scripts/hash_evidence.py
"""

from __future__ import annotations

import hashlib
from pathlib import Path

EVIDENCE = Path(__file__).resolve().parents[1] / "manifests" / "evidence"
SKIP = {".gitkeep", "SHA256SUMS.txt"}


def build_index(evidence: Path = EVIDENCE) -> str:
    """The text ``SHA256SUMS.txt`` should contain for the files currently under ``evidence``."""
    entries: list[tuple[str, str]] = []
    for path in evidence.rglob("*"):
        if path.is_file() and path.name not in SKIP:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            entries.append((path.relative_to(evidence).as_posix(), digest))
    entries.sort()
    return "".join(f"{digest}  {rel}\n" for rel, digest in entries)


def main() -> None:
    text = build_index()
    (EVIDENCE / "SHA256SUMS.txt").write_bytes(text.encode("ascii"))
    print(f"wrote {text.count(chr(10))} entries to {EVIDENCE / 'SHA256SUMS.txt'}")


if __name__ == "__main__":
    main()
