"""Embedding cache keyed by image SHA-256, model, preprocessing version and backend (M3B).

An embedding is never computed twice for the same key. The key has four parts because each of them
changes the numbers: the image bytes (``sha256``), the model (id and pinned revision), the
preprocessing (``preprocessing_version``) and the inference backend (for example ``cpu-fp32``).
Results of different backends are never mixed: each backend has its own directory.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import cast

import numpy as np
from numpy.typing import NDArray

SHA256_RE = re.compile(r"[0-9a-f]{64}")
SEGMENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._@-]*")


def _segment(value: str, what: str) -> str:
    if not SEGMENT_RE.fullmatch(value) or ".." in value:
        raise ValueError(f"invalid {what} {value!r} for a cache path")
    return value


class EmbeddingCache:
    """One float32 vector per file, in ``<root>/embeddings/<model>/<preprocessing>/<backend>/``."""

    def __init__(
        self, root: Path, *, model_key: str, preprocessing_version: str, backend: str, dim: int
    ) -> None:
        self.dim = dim
        self.directory = (
            root
            / "embeddings"
            / _segment(model_key, "model key")
            / _segment(preprocessing_version, "preprocessing version")
            / _segment(backend, "backend")
        )

    def path_for(self, sha256: str) -> Path:
        if not SHA256_RE.fullmatch(sha256):
            raise ValueError(f"not a SHA-256: {sha256!r}")
        return self.directory / sha256[:2] / f"{sha256}.npy"

    def get(self, sha256: str) -> NDArray[np.float32] | None:
        """The cached vector, or ``None`` when absent or unusable (a bad file is simply a miss)."""
        path = self.path_for(sha256)
        if not path.is_file():
            return None
        try:
            vector = np.load(path, allow_pickle=False)
        except (OSError, ValueError, EOFError):
            return None
        if not self._valid(vector):
            return None
        return cast(NDArray[np.float32], vector)

    def put(self, sha256: str, vector: NDArray[np.float32]) -> None:
        if not self._valid(vector):
            raise ValueError("an embedding must be a finite float32 vector of the model's size")
        path = self.path_for(sha256)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        with temporary.open("wb") as handle:
            np.save(handle, vector, allow_pickle=False)
        os.replace(temporary, path)

    def _valid(self, vector: object) -> bool:
        return (
            isinstance(vector, np.ndarray)
            and vector.dtype == np.float32
            and vector.shape == (self.dim,)
            and bool(np.isfinite(vector).all())
        )

    def stats(self) -> tuple[int, int]:
        """(number of cached vectors, total size of their files in bytes)."""
        count = size = 0
        if self.directory.is_dir():
            for path in self.directory.rglob("*.npy"):
                count += 1
                size += path.stat().st_size
        return count, size

    def write_meta(self, meta: dict[str, object]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        text = json.dumps(meta, indent=2, sort_keys=True) + "\n"
        (self.directory / "meta.json").write_bytes(text.encode("utf-8"))
