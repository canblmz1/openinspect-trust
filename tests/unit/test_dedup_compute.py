from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest
from numpy.typing import NDArray
from PIL import ImageEnhance

from openinspect.dedup.cache import EmbeddingCache
from openinspect.dedup.compute import (
    ComputeError,
    FeatureSet,
    HashStore,
    compute_features,
    normalize_rows,
)
from openinspect.dedup.embedder import Embedder, EmbedderError, EmbedderSpec
from openinspect.dedup.hashing import hash_hex
from openinspect.dedup.inventory import ImageItem
from tests.dedup_helpers import (
    DIM,
    Spec,
    StubEmbedder,
    corrupt_copy,
    make_image,
    make_spec,
    write_items,
)


class Setup:
    def __init__(self, tmp_path: Path) -> None:
        self.data = tmp_path / "data"
        self.spec = make_spec()
        self.cache = EmbeddingCache(
            self.data,
            model_key=self.spec.model_key,
            preprocessing_version=self.spec.preprocessing_version,
            backend=self.spec.backend,
            dim=self.spec.dim,
        )
        self.hash_path = self.data / "m3" / "hashes.jsonl"
        self.stub = StubEmbedder(self.spec)

    def items(self) -> list[ImageItem]:
        base = make_image(1)
        return write_items(
            self.data,
            "src",
            [
                Spec("a/1.png", base, "train"),
                Spec("a/2.png", ImageEnhance.Brightness(base).enhance(1.03), "val"),
                Spec("b/1.png", make_image(2), "train"),
                Spec("b/2.png", make_image(3), "test"),
                Spec("c/1.png", make_image(4), None),
            ],
        )

    def run(
        self,
        items: list[ImageItem],
        *,
        factory: Callable[[], Embedder] | str | None = "stub",
        batch_size: int = 2,
        progress: list[str] | None = None,
    ) -> FeatureSet:
        make: Callable[[], Embedder] | None = (
            (lambda: self.stub) if factory == "stub" else factory  # type: ignore[assignment]
        )
        return compute_features(
            items,
            spec=self.spec,
            cache=self.cache,
            hashes=HashStore(self.hash_path),
            make_embedder=make,
            batch_size=batch_size,
            workers=2,
            progress=progress.append if progress is not None else None,
        )


@pytest.fixture
def setup(tmp_path: Path) -> Setup:
    return Setup(tmp_path)


def test_features_are_normalised_hashed_and_cached(setup: Setup) -> None:
    items = setup.items()
    result = setup.run(items)
    assert [i.key for i in result.items] == [i.key for i in items]
    assert result.vectors.shape == (5, DIM)
    assert np.allclose(np.linalg.norm(result.vectors, axis=1), 1.0, atol=1e-5)
    assert result.phash.dtype == np.uint64
    assert result.dhash.dtype == np.uint64
    stats = result.stats
    assert stats is not None
    assert (stats.items, stats.embedded, stats.cache_hits, stats.failed) == (5, 5, 0, 0)
    assert setup.stub.images == 5
    assert setup.stub.calls == 3  # batches of 2, 2 and 1
    assert stats.cache_files == 5
    assert stats.cache_bytes > 0
    assert stats.images_per_second is not None
    assert stats.model_images_per_second is not None
    # a transformed copy is closer to its original than an unrelated image
    sim = result.vectors @ result.vectors.T
    assert sim[0, 1] > 0.98
    assert sim[0, 1] > sim[0, 2] + 0.05


def test_a_second_run_needs_no_model_and_gives_the_same_numbers(setup: Setup) -> None:
    items = setup.items()
    first = setup.run(items)
    calls = setup.stub.calls
    second = setup.run(items, factory=None)  # no model available: everything comes from the caches
    assert setup.stub.calls == calls
    assert second.stats is not None
    assert (second.stats.cache_hits, second.stats.embedded) == (5, 0)
    assert np.array_equal(first.vectors, second.vectors)
    assert np.array_equal(first.phash, second.phash)


def test_the_model_is_not_built_when_nothing_is_missing(setup: Setup) -> None:
    items = setup.items()
    setup.run(items)

    def explode() -> Embedder:
        raise AssertionError("the model must not be loaded for a full cache")

    setup.run(items, factory=explode)


def test_missing_embeddings_without_a_model_is_an_error(setup: Setup) -> None:
    with pytest.raises(ComputeError, match="no embedding in the cache"):
        setup.run(setup.items(), factory=None)


def test_a_model_for_another_specification_is_refused(setup: Setup) -> None:
    other = StubEmbedder(make_spec(revision="1" * 40))
    with pytest.raises(ComputeError, match="does not match"):
        setup.run(setup.items(), factory=lambda: other)


def test_identical_content_is_embedded_once(setup: Setup) -> None:
    image = make_image(9)
    items = write_items(
        setup.data, "src", [Spec("x/1.png", image, "train"), Spec("x/2.png", image, "val")]
    )
    assert items[0].sha256 == items[1].sha256
    result = setup.run(items)
    assert setup.stub.images == 1
    assert result.stats is not None
    assert result.stats.unique_images == 2 - 1
    assert np.array_equal(result.vectors[0], result.vectors[1])


def test_broken_and_changed_files_are_failures_and_the_run_goes_on(setup: Setup) -> None:
    items = setup.items()
    broken = corrupt_copy(items[1])  # bytes that are not an image, hash recorded correctly
    changed = items[2]
    changed.path.write_bytes(changed.path.read_bytes() + b"x")  # no longer the recorded file
    result = setup.run([items[0], broken, changed, items[3]])
    assert [i.item_id for i in result.items] == ["a/1.png", "b/2.png"]
    by_item = {f.item_id: f for f in result.failures}
    assert by_item["a/2.png"].stage == "decode"
    assert by_item["b/1.png"].stage == "read"
    assert "differs from the recorded" in by_item["b/1.png"].error
    assert result.stats is not None
    assert result.stats.failed == 2
    assert result.vectors.shape == (2, DIM)
    again = setup.run([items[0], broken, changed, items[3]], factory=None)
    assert {f.item_id for f in again.failures} == {
        "a/2.png",
        "b/1.png",
    }  # still reported, never fatal


def test_a_missing_file_is_a_read_failure(setup: Setup) -> None:
    items = setup.items()
    items[0].path.unlink()
    result = setup.run(items)
    assert [f.stage for f in result.failures] == ["read"]
    assert len(result.items) == 4


def test_an_embedding_that_is_not_finite_is_a_failure(setup: Setup) -> None:
    class Bad(StubEmbedder):
        def embed(self, batch: NDArray[np.float32]) -> NDArray[np.float32]:
            out = super().embed(batch)
            out[0, 0] = np.nan
            return out

    items = setup.items()[:2]
    bad = Bad(setup.spec)
    result = setup.run(items, factory=lambda: bad, batch_size=2)
    assert [f.stage for f in result.failures] == ["embed"]
    assert len(result.items) == 1


def test_a_model_returning_the_wrong_shape_stops_the_run(setup: Setup) -> None:
    class Wrong(StubEmbedder):
        def embed(self, batch: NDArray[np.float32]) -> NDArray[np.float32]:
            return super().embed(batch)[:, :-1]

    wrong = Wrong(setup.spec)
    with pytest.raises(EmbedderError, match="expected"):
        setup.run(setup.items(), factory=lambda: wrong)


def test_the_hash_store_is_a_deterministic_sorted_file(setup: Setup) -> None:
    items = setup.items()
    setup.run(items)
    first = setup.hash_path.read_bytes()
    lines = first.decode("utf-8").splitlines()
    assert lines == sorted(lines)
    assert len(lines) == 5
    setup.run(items)
    assert setup.hash_path.read_bytes() == first
    store = HashStore(setup.hash_path)
    assert store.get(items[0].sha256) is not None
    assert hash_hex(store.get(items[0].sha256) or 0) in first.decode("utf-8")
    # losing the hash file costs a decode, not an embedding
    setup.hash_path.unlink()
    images_before = setup.stub.images
    setup.run(items, factory=None)
    assert setup.stub.images == images_before
    assert setup.hash_path.read_bytes() == first


def test_progress_is_reported(setup: Setup) -> None:
    messages: list[str] = []
    setup.run(setup.items(), progress=messages)
    assert messages
    assert messages[-1].startswith("5/5 images decoded")


def test_empty_input_gives_empty_features(setup: Setup) -> None:
    result = setup.run([], factory=None)
    assert result.vectors.shape == (0, DIM)
    assert result.items == []


def test_normalize_rows_rejects_a_zero_vector() -> None:
    good = normalize_rows(np.array([[3.0, 4.0]], dtype=np.float32))
    assert np.allclose(good, [[0.6, 0.8]])
    with pytest.raises(ComputeError, match="zero length"):
        normalize_rows(np.zeros((1, 3), dtype=np.float32))


def test_spec_properties() -> None:
    spec: EmbedderSpec = make_spec()
    assert spec.model_key == "stub--model@000000000000"
    assert spec.describe()["backend"] == "cpu-fp32"
