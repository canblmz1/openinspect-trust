from __future__ import annotations

import random
from pathlib import Path

import numpy as np
import pytest

from openinspect.dedup.cache import EmbeddingCache
from openinspect.dedup.compute import HashStore, compute_features
from openinspect.dedup.inventory import ImageItem
from openinspect.dedup.synthetic import (
    SyntheticError,
    compute_synthetic,
    read_pairs,
    sample_for_synthetic,
    synthetic_key,
    write_pairs,
)
from openinspect.dedup.transforms import BY_NAME, TRANSFORMS
from tests.dedup_helpers import Spec, StubEmbedder, make_image, make_spec, write_items


def cache_for(root: Path, spec_name: str = "stub") -> EmbeddingCache:
    spec = make_spec(name=spec_name)
    return EmbeddingCache(
        root,
        model_key=spec.model_key,
        preprocessing_version=spec.preprocessing_version,
        backend=spec.backend,
        dim=spec.dim,
    )


class Setup:
    def __init__(self, tmp_path: Path) -> None:
        self.data = tmp_path / "data"
        self.spec = make_spec()
        self.stub = StubEmbedder(self.spec)
        self.originals = cache_for(self.data)
        self.synthetic = cache_for(self.data / "synthetic")
        self.items: list[ImageItem] = write_items(
            self.data,
            "src",
            [Spec(f"img/{k}.png", make_image(k, size=(120, 90))) for k in range(4)],
        )
        compute_features(
            self.items,
            spec=self.spec,
            cache=self.originals,
            hashes=HashStore(self.data / "hashes.jsonl"),
            make_embedder=lambda: self.stub,
        )
        self.embedded_before = self.stub.images

    def run(self, *, factory: bool = True, seed: int = 0) -> list:  # type: ignore[type-arg]
        return compute_synthetic(
            self.items,
            originals=self.originals,
            cache=self.synthetic,
            spec=self.spec,
            make_embedder=(lambda: self.stub) if factory else None,
            seed=seed,
            batch_size=5,
        )


@pytest.fixture
def setup(tmp_path: Path) -> Setup:
    return Setup(tmp_path)


def test_every_transform_is_seeded_and_changes_only_what_it_claims() -> None:
    image = make_image(1, size=(200, 150))
    for transform in TRANSFORMS:
        first = transform.apply(image, random.Random("x"))
        again = transform.apply(image, random.Random("x"))
        assert first.tobytes() == again.tobytes(), transform.name
    assert BY_NAME["crop_90"].apply(image, random.Random(0)).size == (180, 135)
    assert BY_NAME["crop_80"].apply(image, random.Random(0)).size == (160, 120)
    assert BY_NAME["jpeg_q75"].apply(image, random.Random(0)).size == image.size
    assert BY_NAME["resample_half"].apply(image, random.Random(0)).size == image.size
    offsets = {BY_NAME["crop_95"].apply(image, random.Random(s)).tobytes() for s in range(6)}
    assert len(offsets) > 1  # different seeds give different fields of view


def test_the_near_duplicate_set_excludes_the_partial_overlap() -> None:
    names = {t.name for t in TRANSFORMS if t.near_duplicate}
    assert "crop_80" not in names
    assert {"jpeg_q75", "blur", "crop_90"} <= names
    assert {t.kind for t in TRANSFORMS} == {"photometric", "geometric", "partial"}


def test_a_transformed_copy_is_close_to_its_original(setup: Setup) -> None:
    pairs = setup.run()
    assert len(pairs) == 4 * len(TRANSFORMS)
    by_transform: dict[str, list[float]] = {}
    for pair in pairs:
        assert -1.0 <= pair.cosine <= 1.0
        by_transform.setdefault(pair.transform, []).append(pair.cosine)
        assert 0 <= pair.phash_distance <= 64
        assert 0 <= pair.dhash_distance <= 64
    assert min(by_transform["jpeg_q75"]) > 0.99
    assert min(by_transform["brightness_up"]) > 0.95
    assert np.mean(by_transform["crop_80"]) < np.mean(by_transform["jpeg_q75"])
    assert {p.source for p in pairs} == {"src"}
    assert {p.item_id for p in pairs} == {i.item_id for i in setup.items}


def test_a_second_run_embeds_nothing_and_gives_identical_pairs(setup: Setup) -> None:
    first = setup.run()
    images = setup.stub.images
    assert images > setup.embedded_before
    second = setup.run(factory=False)  # no model needed: every copy is cached
    assert setup.stub.images == images
    assert first == second


def test_the_cache_key_depends_on_the_whole_recipe(setup: Setup) -> None:
    item = setup.items[0]
    base = synthetic_key(item, BY_NAME["blur"], 0, setup.spec)
    assert base != synthetic_key(item, BY_NAME["blur"], 1, setup.spec)
    assert base != synthetic_key(item, BY_NAME["crop_90"], 0, setup.spec)
    assert base != synthetic_key(setup.items[1], BY_NAME["blur"], 0, setup.spec)
    assert base == synthetic_key(item, BY_NAME["blur"], 0, setup.spec)
    assert len(base) == 64


def test_missing_embeddings_are_errors_not_silent_gaps(setup: Setup, tmp_path: Path) -> None:
    with pytest.raises(SyntheticError, match="synthetic embeddings are missing"):
        setup.run(factory=False)
    setup.originals.path_for(setup.items[0].sha256).unlink()
    with pytest.raises(SyntheticError, match="no embedding for"):
        setup.run()


def test_the_sample_is_seeded_per_source_and_keeps_small_sources_whole() -> None:
    def make(source: str, n: int) -> list[ImageItem]:
        return [
            ImageItem(
                source, f"{k:04d}.png", Path(f"{k}.png"), f"{k:064x}", None, None, None, 0, 0, 1, 1
            )
            for k in range(n)
        ]

    items = make("a", 50) + make("b", 3)
    first = sample_for_synthetic(items, 10, seed=1)
    assert first == sample_for_synthetic(items, 10, seed=1)
    assert first != sample_for_synthetic(items, 10, seed=2)
    assert [i.source for i in first].count("a") == 10
    assert [i.source for i in first].count("b") == 3
    assert [i.item_id for i in first if i.source == "a"] == sorted(
        i.item_id for i in first if i.source == "a"
    )


def test_pairs_round_trip_through_their_file(setup: Setup, tmp_path: Path) -> None:
    pairs = setup.run()
    path = tmp_path / "out" / "synthetic.jsonl"
    write_pairs(path, pairs)
    assert read_pairs(path) == pairs
    first = path.read_bytes()
    write_pairs(path, pairs)
    assert path.read_bytes() == first
    with pytest.raises(SyntheticError, match="is missing"):
        read_pairs(tmp_path / "nothing.jsonl")
