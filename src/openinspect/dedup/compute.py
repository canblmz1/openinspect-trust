"""Hashes and embeddings of every image, with caching and per-image failure handling (M3A, M3B).

Each image is decoded at most once per run, and only when something is missing from the caches:
its embedding (keyed by SHA-256, model, preprocessing and backend) or its perceptual hash. A file
that cannot be read, fails its SHA-256 check or decodes badly is recorded as a failure and left
out; it never stops the run and is never deleted.
"""

from __future__ import annotations

import json
import os
import time
from collections import deque
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from openinspect.dedup.cache import SHA256_RE, EmbeddingCache
from openinspect.dedup.embedder import Embedder, EmbedderError, EmbedderSpec
from openinspect.dedup.features import (
    DecodeError,
    ReadError,
    decode_rgb,
    preprocess,
    read_verified,
)
from openinspect.dedup.hashing import PHASH_VERSION, hash_hex, phash_int
from openinspect.dedup.inventory import ImageItem

Progress = Callable[[str], None]


class ComputeError(Exception):
    """The features cannot be produced (for example embeddings are missing and no model is available)."""


@dataclass(frozen=True)
class Failure:
    source: str
    item_id: str
    sha256: str
    stage: str  # read | decode | embed
    error: str


@dataclass(frozen=True)
class ComputeStats:
    items: int
    unique_images: int
    cache_hits: int
    embedded: int
    failed: int
    embed_seconds: float  # time inside the model
    wall_seconds: float  # the whole call: decode, hash, model, cache
    cache_files: int
    cache_bytes: int

    @property
    def images_per_second(self) -> float | None:
        """Throughput of the images that had to be computed (decode + hash + model)."""
        return self.embedded / self.wall_seconds if self.embedded and self.wall_seconds else None

    @property
    def model_images_per_second(self) -> float | None:
        """Throughput of the model alone."""
        return self.embedded / self.embed_seconds if self.embedded and self.embed_seconds else None


@dataclass(frozen=True)
class FeatureSet:
    items: list[ImageItem]  # images that have features, in input order
    vectors: NDArray[np.float32]  # (n, dim), L2-normalised
    phash: NDArray[np.uint64]
    dhash: NDArray[np.uint64]
    failures: list[Failure] = field(default_factory=list)
    stats: ComputeStats | None = None


class HashStore:
    """Perceptual hashes by image SHA-256, persisted as sorted JSON lines (deterministic file)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._values: dict[str, int] = {}
        self._dirty = False
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                if SHA256_RE.fullmatch(row["sha256"]) and len(row["phash"]) == 16:
                    self._values[row["sha256"]] = int(row["phash"], 16)

    def get(self, sha256: str) -> int | None:
        return self._values.get(sha256)

    def put(self, sha256: str, value: int) -> None:
        if self._values.get(sha256) != value:
            self._values[sha256] = value
            self._dirty = True

    def save(self) -> None:
        if not self._dirty and self.path.is_file():
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            json.dumps({"sha256": sha, "phash": hash_hex(value), "version": PHASH_VERSION})
            for sha, value in sorted(self._values.items())
        ]
        temporary = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
        temporary.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
        os.replace(temporary, self.path)
        self._dirty = False


def _stored_phash(hashes: HashStore, item: ImageItem) -> int:
    value = hashes.get(item.sha256)
    if value is None:  # pragma: no cover - every kept image was hashed or failed
        raise ComputeError(f"no perceptual hash for {item.source}:{item.item_id}")
    return value


def normalize_rows(vectors: NDArray[np.float32]) -> NDArray[np.float32]:
    """L2-normalise every row; a zero vector is an error (it has no direction)."""
    norms = np.linalg.norm(vectors.astype(np.float64), axis=1, keepdims=True)
    if (norms == 0).any():
        raise ComputeError("an embedding has zero length")
    return (vectors / norms).astype(np.float32)


@dataclass(frozen=True)
class _Prepared:
    sha256: str
    pixels: NDArray[np.float32] | None
    phash: int | None
    error: tuple[str, str] | None  # (stage, message)


def _prepare(item: ImageItem, *, need_pixels: bool, need_phash: bool) -> _Prepared:
    try:
        image = decode_rgb(read_verified(item.path, item.sha256))
    except DecodeError as exc:
        stage = "read" if isinstance(exc, ReadError) else "decode"
        return _Prepared(item.sha256, None, None, (stage, str(exc)))
    return _Prepared(
        item.sha256,
        preprocess(image) if need_pixels else None,
        phash_int(image) if need_phash else None,
        None,
    )


def _chunks(
    work: Sequence[tuple[ImageItem, bool, bool]], size: int
) -> Iterator[list[tuple[ImageItem, bool, bool]]]:
    for start in range(0, len(work), size):
        yield list(work[start : start + size])


def compute_features(
    items: Sequence[ImageItem],
    *,
    spec: EmbedderSpec,
    cache: EmbeddingCache,
    hashes: HashStore,
    make_embedder: Callable[[], Embedder] | None,
    batch_size: int = 32,
    workers: int = 2,
    progress: Progress | None = None,
) -> FeatureSet:
    """Features for ``items``. The model is only built (``make_embedder``) when an embedding is missing."""
    started = time.perf_counter()
    embed_seconds = 0.0
    unique: dict[str, ImageItem] = {}
    for item in items:
        unique.setdefault(item.sha256, item)

    vectors: dict[str, NDArray[np.float32]] = {}
    failed: dict[str, tuple[str, str]] = {}
    work: list[tuple[ImageItem, bool, bool]] = []
    for sha, item in unique.items():
        cached = cache.get(sha)
        if cached is not None:
            vectors[sha] = cached
        need_phash = hashes.get(sha) is None
        if cached is None or need_phash:
            work.append((item, cached is None, need_phash))
    cache_hits = len(vectors)
    embedder: Embedder | None = None
    n_pending = sum(1 for _, need_pixels, _ in work if need_pixels)

    embedded = 0
    done = 0
    batches_done = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        lookahead: deque[tuple[list[tuple[ImageItem, bool, bool]], list[Future[_Prepared]]]] = (
            deque()
        )
        batches = _chunks(work, batch_size)

        def submit_next() -> None:
            batch = next(batches, None)
            if batch is not None:
                lookahead.append(
                    (
                        batch,
                        [
                            pool.submit(_prepare, it, need_pixels=p, need_phash=h)
                            for it, p, h in batch
                        ],
                    )
                )

        for _ in range(2):
            submit_next()
        while lookahead:
            batch, futures = lookahead.popleft()
            submit_next()
            prepared = [future.result() for future in futures]
            ready: list[tuple[str, NDArray[np.float32]]] = []
            for (item, need_pixels, _), result in zip(batch, prepared, strict=True):
                if result.error is not None:
                    failed[item.sha256] = result.error
                    continue
                if result.phash is not None:
                    hashes.put(item.sha256, result.phash)
                if need_pixels and result.pixels is not None:
                    ready.append((item.sha256, result.pixels))
            if ready:
                if embedder is None:
                    if make_embedder is None:
                        raise ComputeError(
                            f"{n_pending} images have no embedding in the cache for "
                            f"{spec.model_key}/{spec.preprocessing_version}/{spec.backend}; "
                            "run `openinspect dedup features` first"
                        )
                    embedder = make_embedder()
                    if embedder.spec != spec:
                        raise ComputeError(
                            "the embedder does not match the requested model specification"
                        )
                tick = time.perf_counter()
                raw = embedder.embed(np.stack([pixels for _, pixels in ready]))
                embed_seconds += time.perf_counter() - tick
                if raw.shape != (len(ready), spec.dim):
                    raise EmbedderError(
                        f"expected {(len(ready), spec.dim)} vectors, got {raw.shape}"
                    )
                for (sha, _), row in zip(ready, raw, strict=True):
                    vector = np.ascontiguousarray(row, dtype=np.float32)
                    if not np.isfinite(vector).all():
                        failed[sha] = ("embed", "the model returned non-finite values")
                        continue
                    cache.put(sha, vector)
                    vectors[sha] = vector
                    embedded += 1
            done += len(batch)
            batches_done += 1
            if progress is not None and (batches_done % 10 == 0 or not lookahead):
                progress(f"{done}/{len(work)} images decoded ({embedded} embedded)")
    hashes.save()
    if embedded:
        cache.write_meta({**spec.describe(), "note": "raw CLS vectors; L2-normalised on load"})

    kept: list[ImageItem] = []
    failures: list[Failure] = []
    for item in items:
        if item.sha256 in failed:
            stage, message = failed[item.sha256]
            failures.append(Failure(item.source, item.item_id, item.sha256, stage, message))
        else:
            kept.append(item)
    matrix = (
        normalize_rows(np.stack([vectors[item.sha256] for item in kept]))
        if kept
        else np.empty((0, spec.dim), dtype=np.float32)
    )
    phash = np.array([_stored_phash(hashes, item) for item in kept], dtype=np.uint64)
    dhash = np.array(
        [item.dhash if item.dhash is not None else 0 for item in kept], dtype=np.uint64
    )
    count, size = cache.stats()
    stats = ComputeStats(
        items=len(items),
        unique_images=len(unique),
        cache_hits=cache_hits,
        embedded=embedded,
        failed=len(failures),
        embed_seconds=embed_seconds,
        wall_seconds=time.perf_counter() - started,
        cache_files=count,
        cache_bytes=size,
    )
    return FeatureSet(kept, matrix, phash, dhash, failures, stats)
