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

from openinspect.dedup.compute import FeatureSet
from openinspect.dedup.embedder import EmbedderSpec
from openinspect.dedup.inventory import ImageItem
from openinspect.dedup.synthetic import SyntheticPair
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


# ------------------------------------------------------------ features without images


def _unit(rng: np.random.Generator, dim: int) -> NDArray[np.float64]:
    v = rng.standard_normal(dim)
    return v / np.linalg.norm(v)


def _near(
    rng: np.random.Generator, centre: NDArray[np.float64], noise: float
) -> NDArray[np.float64]:
    v = centre + noise * rng.standard_normal(len(centre))
    return v / np.linalg.norm(v)


@dataclass
class Clustered:
    """A feature set with planted structure, and synthetic pairs for it (no image is read)."""

    features: FeatureSet
    synthetic: list[SyntheticPair]


def clustered_features(seed: int = 0, dim: int = 16) -> Clustered:
    """Three sources named like the real ones, with the structure the audit must find.

    * ``dspcbsd-plus``: 40 images, train/val; eight tight clusters of three (four cross train|val),
      one exact duplicate, the rest unrelated.
    * ``pcb-ind``: 60 images in 12 (batch, side) groups of five (6 batches x 2 sides), each group in
      one split; the two sides of batch b5 in different splits; one near-identical pair across
      batches b0 (train) and b3 (test), which the key cannot see.
    * ``pcb-defect``: 24 images, 3 families x 2 subgroups x 4, no split.
    """
    rng = np.random.default_rng(seed)
    rows: list[tuple[str, str, str | None, str | None, str | None, NDArray[np.float64]]] = []
    # dspcbsd-plus
    for c in range(8):
        centre = _unit(rng, dim)
        for m in range(3):
            split = "val" if (c < 4 and m == 2) else "train"
            rows.append(
                ("dspcbsd-plus", f"S_{c:02d}_{m}.jpg", split, None, None, _near(rng, centre, 0.02))
            )
    for k in range(15):
        rows.append(
            (
                "dspcbsd-plus",
                f"S_x{k:02d}.jpg",
                "val" if k < 4 else "train",
                None,
                None,
                _unit(rng, dim),
            )
        )
    # pcb-ind
    side_split = {
        (0, "b"): "train",
        (0, "t"): "train",
        (1, "b"): "train",
        (1, "t"): "train",
        (2, "b"): "val",
        (2, "t"): "val",
        (3, "b"): "test",
        (3, "t"): "test",
        (4, "b"): "train",
        (4, "t"): "train",
        (5, "b"): "train",
        (5, "t"): "val",
    }
    ind_centres: dict[tuple[int, str], NDArray[np.float64]] = {}
    for batch in range(6):
        for side in ("b", "t"):
            centre = _unit(rng, dim)
            ind_centres[(batch, side)] = centre
            for m in range(5):
                rows.append(
                    (
                        "pcb-ind",
                        f"YOLO/{batch:04d}_{side}_{m:03d}.jpg",
                        side_split[(batch, side)],
                        f"{batch:04d}",
                        f"{batch:04d}_{side}",
                        _near(rng, centre, 0.08),
                    )
                )
    # the cross-batch twin: b3/t member 4 looks like b0/b member 0
    twin = next(i for i, r in enumerate(rows) if r[1] == "YOLO/0003_t_004.jpg")
    base = next(r for r in rows if r[1] == "YOLO/0000_b_000.jpg")
    rows[twin] = (*rows[twin][:5], _near(rng, base[5], 0.01))
    # pcb-defect
    for family in range(3):
        f_centre = _unit(rng, dim)
        for b in range(2):
            s_centre = _near(rng, f_centre, 0.35)
            for m in range(4):
                rows.append(
                    (
                        "pcb-defect",
                        f"images/{family + 1:02d}-{b + 1}-{m:02d}.png",
                        None,
                        f"{family + 1:02d}",
                        f"{family + 1:02d}-{b + 1}",
                        _near(rng, s_centre, 0.05),
                    )
                )
    rows.sort(key=lambda r: (r[0], r[1]))
    items: list[ImageItem] = []
    for index, (source, item_id, item_split, group, sub, _) in enumerate(rows):
        sha = hashlib.sha256(f"{source}:{item_id}".encode()).hexdigest()
        items.append(
            ImageItem(
                source,
                item_id,
                Path("missing") / source / item_id,
                sha,
                item_split,
                group,
                sub,
                1 + index % 3,
                None,
                64,
                64,
            )
        )
    vectors = np.array([r[5] for r in rows], dtype=np.float32)
    # one exact duplicate inside dspcbsd-plus: same bytes, same vector
    dup = next(i for i, item in enumerate(items) if item.item_id == "S_x05.jpg")
    src = next(i for i, item in enumerate(items) if item.item_id == "S_x04.jpg")
    items[dup] = ImageItem(**{**items[dup].__dict__, "sha256": items[src].sha256})
    vectors[dup] = vectors[src]
    vectors /= np.linalg.norm(vectors.astype(np.float64), axis=1, keepdims=True).astype(np.float32)
    hash_rng = np.random.default_rng(seed + 1)
    phash = hash_rng.integers(0, 2**63, size=len(items), dtype=np.int64).astype(np.uint64)
    dhash = hash_rng.integers(0, 2**63, size=len(items), dtype=np.int64).astype(np.uint64)
    phash[dup], dhash[dup] = phash[src], dhash[src]
    # a pair whose hashes agree while the embeddings do not (hash hint, "hash and embedding disagree")
    a = next(i for i, item in enumerate(items) if item.item_id == "S_x07.jpg")
    b = next(i for i, item in enumerate(items) if item.item_id == "S_x08.jpg")
    phash[b] = phash[a] ^ np.uint64(0b11)
    features = FeatureSet(items, vectors.astype(np.float32), phash, dhash)
    synthetic: list[SyntheticPair] = []
    for source in ("dspcbsd-plus", "pcb-defect", "pcb-ind"):
        own = [item for item in items if item.source == source][:5]
        for item in own:
            for name, kind, near_dup, cosine, bits in (
                ("jpeg_q75", "photometric", True, 0.999, 1),
                ("brightness_up", "photometric", True, 0.995, 2),
                ("blur", "photometric", True, 0.990, 3),
                ("crop_90", "geometric", True, 0.985, 12),
                ("crop_80", "partial", False, 0.95, 20),
            ):
                synthetic.append(
                    SyntheticPair(
                        source, item.item_id, item.sha256, name, kind, near_dup, cosine, bits, bits
                    )
                )
    return Clustered(features, synthetic)
