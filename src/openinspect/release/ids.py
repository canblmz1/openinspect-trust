"""Global ids: stable across rebuilds, independent of file names and of the rest of the pool (T33).

``OI_<source>_<12 hex>``: the hex is the start of a SHA-256 over the source id and the image's
content hash, plus the crop rectangle for a crop. Adding or removing other items never changes an
id, and renaming or moving a file never does either. A collision is checked, not assumed away.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

HEX = 12
ID_PATTERN = re.compile(r"^OI_[a-z0-9]+(?:-[a-z0-9]+)*_[0-9a-f]{12}$")


class IdCollisionError(Exception):
    """Two different items received the same global id."""


def global_id(
    source: str, content_sha256: str, crop: tuple[int, int, int, int] | None = None
) -> str:
    key = f"{source}:{content_sha256}"
    if crop is not None:
        key += ":crop:" + ",".join(str(v) for v in crop)
    return f"OI_{source}_{hashlib.sha256(key.encode('utf-8')).hexdigest()[:HEX]}"


def check_unique(ids: Iterable[str]) -> None:
    seen: set[str] = set()
    for value in ids:
        if value in seen:
            raise IdCollisionError(f"global id {value} is assigned twice")
        seen.add(value)
