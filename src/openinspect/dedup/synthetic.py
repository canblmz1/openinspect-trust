"""Similarity of images to their own transformed copies (M3D, synthetic positives)."""

from __future__ import annotations

import hashlib
import json
import os
import random
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from openinspect.dedup.cache import EmbeddingCache
from openinspect.dedup.compute import Progress, normalize_rows
from openinspect.dedup.embedder import Embedder, EmbedderError, EmbedderSpec
from openinspect.dedup.features import decode_rgb, preprocess, read_verified
from openinspect.dedup.hashing import PHASH_VERSION, hamming, phash_int
from openinspect.dedup.inventory import ImageItem
from openinspect.dedup.transforms import TRANSFORMS, Transform
from openinspect.ingest.imaging import dhash64


class SyntheticError(Exception):
    """The synthetic positives cannot be produced."""


@dataclass(frozen=True)
class SyntheticPair:
    source: str
    item_id: str
    sha256: str
    transform: str
    kind: str
    near_duplicate: bool
    cosine: float
    phash_distance: int
    dhash_distance: int


def synthetic_key(item: ImageItem, transform: Transform, seed: int, spec: EmbedderSpec) -> str:
    """Cache key of one transformed copy: a hash of everything that decides its pixels."""
    text = "|".join(
        [
            "synthetic",
            item.sha256,
            transform.name,
            str(seed),
            spec.preprocessing_version,
            PHASH_VERSION,
        ]
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sample_for_synthetic(items: Sequence[ImageItem], per_source: int, seed: int) -> list[ImageItem]:
    chosen: list[ImageItem] = []
    for source in sorted({item.source for item in items}):
        pool = [item for item in items if item.source == source]
        if len(pool) > per_source:
            rng = random.Random(f"synthetic:{seed}:{source}")  # noqa: S311 - reproducible sampling
            pool = [pool[i] for i in sorted(rng.sample(range(len(pool)), per_source))]
        chosen.extend(pool)
    return chosen


def compute_synthetic(
    items: Sequence[ImageItem],
    *,
    originals: EmbeddingCache,
    cache: EmbeddingCache,
    spec: EmbedderSpec,
    make_embedder: Callable[[], Embedder] | None,
    seed: int = 0,
    batch_size: int = 32,
    progress: Progress | None = None,
) -> list[SyntheticPair]:
    """Cosine similarity and hash distances between each image and each transformed copy of it."""
    pairs: list[SyntheticPair] = []
    embedder: Embedder | None = None
    pending: list[tuple[str, NDArray[np.float32]]] = []  # (cache key, pixels) waiting for the model
    rows: list[tuple[ImageItem, Transform, str, int, int, NDArray[np.float32]]] = []
    vectors: dict[str, NDArray[np.float32]] = {}

    def flush() -> None:
        nonlocal embedder
        if not pending:
            return
        if make_embedder is None:
            raise SyntheticError(
                "synthetic embeddings are missing; run `openinspect dedup synthetic`"
            )
        if embedder is None:
            embedder = make_embedder()
        raw = embedder.embed(np.stack([pixels for _, pixels in pending]))
        if raw.shape != (len(pending), spec.dim) or not np.isfinite(raw).all():
            raise EmbedderError("the model returned an unusable batch for synthetic copies")
        for (key, _), row in zip(pending, raw, strict=True):
            vector = np.ascontiguousarray(row, dtype=np.float32)
            cache.put(key, vector)
            vectors[key] = vector
        pending.clear()

    for index, item in enumerate(items):
        original = originals.get(item.sha256)
        if original is None:
            raise SyntheticError(
                f"no embedding for {item.source}:{item.item_id}; run `dedup features`"
            )
        image = decode_rgb(read_verified(item.path, item.sha256))
        base_phash = phash_int(image)
        base_dhash = int(dhash64(image), 16)
        normalised = normalize_rows(original[None, :])[0]
        for transform in TRANSFORMS:
            copy = transform.apply(image, random.Random(f"{seed}:{item.sha256}:{transform.name}"))  # noqa: S311
            key = synthetic_key(item, transform, seed, spec)
            cached = cache.get(key)
            if cached is not None:
                vectors[key] = cached
            else:
                pending.append((key, preprocess(copy)))
            rows.append(
                (
                    item,
                    transform,
                    key,
                    hamming(base_phash, phash_int(copy)),
                    hamming(base_dhash, int(dhash64(copy), 16)),
                    normalised,
                )
            )
            if len(pending) >= batch_size:
                flush()
        if progress is not None and (index + 1) % 50 == 0:
            progress(f"{index + 1}/{len(items)} images transformed")
    flush()
    for item, transform, key, phash_distance, dhash_distance, normalised in rows:
        copy_vector = normalize_rows(vectors[key][None, :])[0]
        pairs.append(
            SyntheticPair(
                source=item.source,
                item_id=item.item_id,
                sha256=item.sha256,
                transform=transform.name,
                kind=transform.kind,
                near_duplicate=transform.near_duplicate,
                cosine=float(
                    np.clip(
                        np.dot(normalised.astype(np.float64), copy_vector.astype(np.float64)),
                        -1.0,
                        1.0,
                    )
                ),
                phash_distance=phash_distance,
                dhash_distance=dhash_distance,
            )
        )
    if cache.directory.is_dir():
        cache.write_meta({**spec.describe(), "note": "synthetic copies, key = hash of the recipe"})
    return pairs


def write_pairs(path: Path, pairs: Sequence[SyntheticPair]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(asdict(pair), sort_keys=True) for pair in pairs]
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    os.replace(temporary, path)


def read_pairs(path: Path) -> list[SyntheticPair]:
    if not path.is_file():
        raise SyntheticError(f"{path.name} is missing; run `openinspect dedup synthetic`")
    return [
        SyntheticPair(**json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines()
    ]
