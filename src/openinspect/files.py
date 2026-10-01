"""Small file helpers shared by the milestone outputs: atomic writes, digests, Parquet."""

from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def replace_bytes(path: Path, data: bytes) -> None:
    """Write ``data`` to a temporary name next to ``path`` and rename it into place."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def parquet_bytes(table: pa.Table) -> bytes:
    """The same table gives the same bytes (fixed codec, dictionary encoding, no timestamps)."""
    buffer = io.BytesIO()
    pq.write_table(table, buffer, compression="zstd", use_dictionary=True)
    return buffer.getvalue()
