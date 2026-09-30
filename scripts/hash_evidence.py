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


def main() -> None:
    entries: list[tuple[str, str]] = []
    for path in EVIDENCE.rglob("*"):
        if path.is_file() and path.name not in SKIP:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            entries.append((path.relative_to(EVIDENCE).as_posix(), digest))
    entries.sort()
    text = "".join(f"{digest}  {rel}\n" for rel, digest in entries)
    (EVIDENCE / "SHA256SUMS.txt").write_bytes(text.encode("ascii"))
    print(f"wrote {len(entries)} entries to {EVIDENCE / 'SHA256SUMS.txt'}")


if __name__ == "__main__":
    main()
