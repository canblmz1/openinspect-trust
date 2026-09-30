"""Synthetic images, a stub embedder and item builders for the duplicate-audit tests.

No test needs torch, the network or a real dataset: the stub embedder maps an image to a fixed
random projection of its low-frequency content, so a transformed copy of an image is close to it
and an unrelated image is not.
"""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from openinspect.dedup.embedder import EmbedderSpec
from openinspect.dedup.inventory import ImageItem
from openinspect.ingest.imaging import dhash64
from openinspect.provenance.records import ImageRecord

DIM = 24


def make_spec(
    *, name: str = "stub", revision: str = "0" * 40, backend: str = "cpu-fp32", dim: int = DIM
) -> EmbedderSpec:
    return EmbedderSpec(
        name=name,
        model_id="stub/model",
        revision=revision,
        preprocessing_version="v1",
        backend=backend,
        dim=dim,
    )


class StubEmbedder:
    """Random projection of the 8x8 average-pooled input: similar images give similar vectors."""

    def __init__(self, spec: EmbedderSpec | None = None) -> None:
        self._spec = spec or make_spec()
        self._projection = (
            np.random.default_rng(1234).standard_normal((192, self._spec.dim)).astype(np.float32)
        )
        self.calls = 0
        self.images = 0

    @property
    def spec(self) -> EmbedderSpec:
        return self._spec

    def embed(self, batch: NDArray[np.float32]) -> NDArray[np.float32]:
        self.calls += 1
        self.images += len(batch)
        n = len(batch)
        pooled = batch.reshape(n, 3, 8, 28, 8, 28).mean(axis=(3, 5)).reshape(n, 192)
        return (pooled @ self._projection).astype(np.float32)


def make_image(seed: int, size: tuple[int, int] = (96, 80)) -> Image.Image:
    """A smooth random colour image; different seeds give unrelated images."""
    rng = np.random.default_rng(seed)
    coarse = (rng.random((6, 6, 3)) * 255).astype(np.uint8)
    return Image.fromarray(coarse).resize(size, Image.Resampling.BICUBIC)


def encode(image: Image.Image, suffix: str = ".png") -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG" if suffix == ".png" else "JPEG", quality=92)
    return buffer.getvalue()


@dataclass(frozen=True)
class Spec:
    item_id: str
    image: Image.Image
    split: str | None = None
    group: str | None = None
    subgroup: str | None = None
    n_annotations: int = 1


def write_items(data_dir: Path, source: str, specs: list[Spec]) -> list[ImageItem]:
    """Write the images under ``<data>/extracted/<source>/`` and return their items (sorted)."""
    items: list[ImageItem] = []
    for spec in specs:
        path = data_dir / "extracted" / source / spec.item_id
        path.parent.mkdir(parents=True, exist_ok=True)
        data = encode(spec.image, path.suffix)
        path.write_bytes(data)
        items.append(
            ImageItem(
                source=source,
                item_id=spec.item_id,
                path=path,
                sha256=hashlib.sha256(data).hexdigest(),
                split=spec.split,
                group=spec.group,
                subgroup=spec.subgroup,
                n_annotations=spec.n_annotations,
                dhash=int(dhash64(spec.image), 16),
                width=spec.image.width,
                height=spec.image.height,
            )
        )
    return sorted(items, key=lambda item: item.key)


def write_records(data_dir: Path, source: str, items: list[ImageItem]) -> None:
    """Write ``records/<source>/images.jsonl`` for items made by :func:`write_items`."""
    folder = data_dir / "records" / source
    folder.mkdir(parents=True, exist_ok=True)
    lines = []
    for item in items:
        record = ImageRecord(
            source_dataset=source,
            source_item_id=item.item_id,
            source_url="https://example.org/record",
            source_license="CC-BY-4.0",
            sha256=item.sha256,
            sha256_source=item.sha256,
            bytes=item.path.stat().st_size,
            decode_ok=True,
            width=item.width,
            height=item.height,
            format="PNG",
            mode="RGB",
            dhash=f"{item.dhash:016x}" if item.dhash is not None else None,
            original_split=item.split,  # type: ignore[arg-type]
            source_group_id=item.group,
            source_subgroup_id=item.subgroup,
            n_annotations=item.n_annotations,
            annotation_source="coco",
        )
        lines.append(record.model_dump_json())
    (folder / "images.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def corrupt_copy(item: ImageItem) -> ImageItem:
    """The same item pointing at a file that is not an image (its hash matches the new bytes)."""
    data = b"this is not an image at all"
    item.path.write_bytes(data)
    return ImageItem(
        source=item.source,
        item_id=item.item_id,
        path=item.path,
        sha256=hashlib.sha256(data).hexdigest(),
        split=item.split,
        group=item.group,
        subgroup=item.subgroup,
        n_annotations=item.n_annotations,
        dhash=item.dhash,
        width=None,
        height=None,
    )


def json_lines(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
