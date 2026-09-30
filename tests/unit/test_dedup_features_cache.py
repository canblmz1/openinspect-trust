from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest
from numpy.typing import NDArray
from PIL import Image

from openinspect.dedup.cache import EmbeddingCache
from openinspect.dedup.features import (
    IMAGENET_MEAN,
    IMAGENET_STD,
    INPUT_SIZE,
    DecodeError,
    IntegrityError,
    ReadError,
    decode_rgb,
    preprocess,
    read_verified,
)
from tests.dedup_helpers import encode, make_image

# ------------------------------------------------------------------------------- preprocessing


def test_preprocessing_is_deterministic_and_has_the_model_shape() -> None:
    image = make_image(1, size=(300, 200))
    first, second = preprocess(image), preprocess(image.copy())
    assert first.shape == (3, INPUT_SIZE, INPUT_SIZE)
    assert first.dtype == np.float32
    assert first.flags["C_CONTIGUOUS"]
    assert np.array_equal(first, second)


def test_a_constant_image_maps_to_the_normalised_constant() -> None:
    image = Image.new("RGB", (40, 30), (255, 0, 128))
    out = preprocess(image)
    expected = (np.array([255, 0, 128], dtype=np.float32) / 255.0 - IMAGENET_MEAN) / IMAGENET_STD
    for channel in range(3):
        assert np.allclose(out[channel], expected[channel], atol=1e-6)


def test_preprocessing_ignores_the_source_mode_and_size() -> None:
    gray = Image.new("L", (10, 10), 77)
    rgb = Image.new("RGB", (500, 40), (77, 77, 77))
    assert np.allclose(preprocess(gray), preprocess(rgb), atol=1e-6)


# ----------------------------------------------------------------------------- reading images


def test_read_verified_returns_bytes_that_match_the_record(tmp_path: Path) -> None:
    data = encode(make_image(2))
    path = tmp_path / "a.png"
    path.write_bytes(data)
    assert read_verified(path, hashlib.sha256(data).hexdigest()) == data


def test_read_verified_refuses_changed_or_missing_files(tmp_path: Path) -> None:
    path = tmp_path / "a.png"
    path.write_bytes(encode(make_image(2)))
    with pytest.raises(IntegrityError, match="differs from the recorded"):
        read_verified(path, "0" * 64)
    with pytest.raises(ReadError, match="cannot read"):
        read_verified(tmp_path / "missing.png", "0" * 64)


def test_decode_rgb_converts_and_rejects_broken_data() -> None:
    gray = Image.new("L", (8, 8), 10)
    decoded = decode_rgb(encode(gray))
    assert decoded.mode == "RGB"
    with pytest.raises(DecodeError):
        decode_rgb(b"not an image")
    truncated = encode(make_image(3), ".jpg")[:40]
    with pytest.raises(DecodeError):
        decode_rgb(truncated)


# ------------------------------------------------------------------------------------ cache


def make_cache(
    root: Path,
    *,
    model_key: str = "stub--model@000000000000",
    preprocessing_version: str = "v1",
    backend: str = "cpu-fp32",
    dim: int = 4,
) -> EmbeddingCache:
    return EmbeddingCache(
        root,
        model_key=model_key,
        preprocessing_version=preprocessing_version,
        backend=backend,
        dim=dim,
    )


SHA = "ab" * 32


def vec(*values: float) -> NDArray[np.float32]:
    return np.array(values, dtype=np.float32)


def test_cache_round_trip_and_miss(tmp_path: Path) -> None:
    cache = make_cache(tmp_path)
    assert cache.get(SHA) is None
    cache.put(SHA, vec(1, 2, 3, 4))
    got = cache.get(SHA)
    assert got is not None
    assert np.array_equal(got, vec(1, 2, 3, 4))
    assert cache.path_for(SHA).parent.name == SHA[:2]
    assert cache.stats()[0] == 1
    assert cache.stats()[1] > 0


def test_each_part_of_the_key_has_its_own_entry(tmp_path: Path) -> None:
    base = make_cache(tmp_path)
    base.put(SHA, vec(1, 0, 0, 0))
    for changed in (
        make_cache(tmp_path, model_key="stub--model@111111111111"),
        make_cache(tmp_path, preprocessing_version="v2"),
        make_cache(tmp_path, backend="cuda-fp16"),
    ):
        assert changed.get(SHA) is None  # never mixed with another model, preprocessing or backend
    other_image = "cd" * 32
    assert base.get(other_image) is None


def test_unusable_cache_files_are_a_miss_and_can_be_replaced(tmp_path: Path) -> None:
    cache = make_cache(tmp_path)
    path = cache.path_for(SHA)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"garbage")
    assert cache.get(SHA) is None
    np.save(path, np.array([1.0, np.nan, 0, 0], dtype=np.float32))
    assert cache.get(SHA) is None  # not finite
    np.save(path, np.zeros(9, dtype=np.float32))
    assert cache.get(SHA) is None  # wrong size
    cache.put(SHA, vec(1, 1, 1, 1))
    assert cache.get(SHA) is not None


def test_cache_rejects_bad_vectors_and_unsafe_keys(tmp_path: Path) -> None:
    cache = make_cache(tmp_path)
    with pytest.raises(ValueError, match="finite float32"):
        cache.put(SHA, vec(1, 2, 3))
    with pytest.raises(ValueError, match="finite float32"):
        cache.put(SHA, np.array([1, 2, 3, 4], dtype=np.float64))
    with pytest.raises(ValueError, match="not a SHA-256"):
        cache.path_for("../../etc/passwd")
    with pytest.raises(ValueError, match="invalid model key"):
        make_cache(tmp_path, model_key="../escape")


def test_cache_writes_leave_no_temporary_files_and_meta_is_json(tmp_path: Path) -> None:
    cache = make_cache(tmp_path)
    cache.put(SHA, vec(1, 2, 3, 4))
    cache.write_meta({"name": "stub", "dim": 4})
    leftovers = [p for p in cache.directory.rglob("*") if p.suffix == ".tmp" or ".tmp" in p.name]
    assert leftovers == []
    assert (cache.directory / "meta.json").read_text(encoding="utf-8").endswith("}\n")
