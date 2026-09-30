"""The embedding model behind a small interface (M3B).

The audit only needs ``embed(batch) -> vectors``. The DINOv2 implementation imports torch lazily,
so everything else (cache reads, analysis, tests with a stub) works without the ``embeddings``
extra installed.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray

from openinspect.dedup.config import DedupConfig, ModelEntry


class EmbedderError(Exception):
    """The embedding model could not be loaded or produced unusable output."""


@dataclass(frozen=True)
class EmbedderSpec:
    """Everything that decides the numbers of an embedding (and therefore its cache key)."""

    name: str  # key in configs/dedup.yaml, for example "dinov2-small"
    model_id: str
    revision: str
    preprocessing_version: str
    backend: str
    dim: int

    @property
    def model_key(self) -> str:
        return f"{self.model_id.replace('/', '--')}@{self.revision[:12]}"

    def describe(self) -> dict[str, object]:
        return {
            "name": self.name,
            "model_id": self.model_id,
            "revision": self.revision,
            "preprocessing_version": self.preprocessing_version,
            "backend": self.backend,
            "dim": self.dim,
        }


def spec_from_config(config: DedupConfig, name: str | None = None) -> EmbedderSpec:
    key, entry = config.model(name)
    return EmbedderSpec(
        name=key,
        model_id=entry.model_id,
        revision=entry.revision,
        preprocessing_version=config.preprocessing.version,
        backend=config.backend,
        dim=entry.dim,
    )


class Embedder(Protocol):
    @property
    def spec(self) -> EmbedderSpec: ...

    def embed(self, batch: NDArray[np.float32]) -> NDArray[np.float32]:
        """Raw (not normalised) vectors, shape (n, spec.dim), for a (n, 3, H, W) batch."""
        ...


def verify_weights(path: Path, expected_sha256: str) -> None:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    if digest.hexdigest() != expected_sha256:
        raise EmbedderError(
            f"{path.name}: SHA-256 {digest.hexdigest()[:12]}... differs from the pinned "
            f"{expected_sha256[:12]}...; refusing to load unverified weights"
        )


class DinoV2Embedder:  # pragma: no cover - needs torch and the downloaded weights (local smoke test)
    """DINOv2 on the CPU. The vector is the final-layer CLS token (``pooler_output``)."""

    def __init__(self, spec: EmbedderSpec, model: Any, torch_module: Any) -> None:
        self._spec = spec
        self._model = model
        self._torch = torch_module

    @property
    def spec(self) -> EmbedderSpec:
        return self._spec

    def embed(self, batch: NDArray[np.float32]) -> NDArray[np.float32]:
        torch = self._torch
        with torch.inference_mode():
            output = self._model(pixel_values=torch.from_numpy(np.ascontiguousarray(batch)))
        vectors: NDArray[np.float32] = output.pooler_output.to(torch.float32).cpu().numpy()
        if vectors.ndim != 2 or vectors.shape[1] != self._spec.dim:
            raise EmbedderError(f"unexpected embedding shape {vectors.shape}")
        return vectors


def load_dinov2(  # pragma: no cover - needs torch and the downloaded weights
    spec: EmbedderSpec, entry: ModelEntry, *, data_dir: Path, threads: int | None = None
) -> DinoV2Embedder:
    """Download (once) and load the pinned DINOv2 weights; safetensors only, hash-verified."""
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    try:
        import torch
        from huggingface_hub import snapshot_download
        from transformers import AutoModel
    except ImportError as exc:
        raise EmbedderError(
            "the embedding model needs the 'embeddings' extra: uv sync --extra embeddings"
        ) from exc
    folder = Path(
        snapshot_download(
            repo_id=entry.model_id,
            revision=entry.revision,
            cache_dir=data_dir / "models",
            allow_patterns=["config.json", entry.weights_file],
        )
    )
    verify_weights(folder / entry.weights_file, entry.weights_sha256)
    if threads is not None:
        torch.set_num_threads(threads)
    model = AutoModel.from_pretrained(folder, use_safetensors=True).eval()
    return DinoV2Embedder(spec, model, torch)
