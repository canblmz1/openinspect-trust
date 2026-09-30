from __future__ import annotations

import io
import random
from pathlib import Path

from PIL import Image

from openinspect.ingest.crosscheck import (
    box_in_bounds,
    locality_test,
    match_boxes,
    nearest_neighbour_test,
)
from openinspect.ingest.formats import Box
from openinspect.ingest.imaging import dhash64, inspect_image
from tests.ingest_fixtures import write_jpeg


def box(label: str, x0: float, y0: float, x1: float, y1: float) -> Box:
    return Box(label, None, x0, y0, x1, y1)


# ------------------------------------------------------------------------------ match_boxes


def test_identical_box_sets_match_with_zero_deviation() -> None:
    boxes = [box("a", 1, 1, 5, 5), box("b", 10, 10, 20, 20)]
    result = match_boxes(boxes, list(reversed(boxes)))
    assert result.deviations == (0.0, 0.0)
    assert (result.only_a, result.only_b, result.max_deviation) == (0, 0, 0.0)


def test_matching_is_one_to_one_and_reports_the_surplus() -> None:
    a = [box("a", 0, 0, 10, 10)]
    b = [box("a", 0, 0, 10, 10), box("a", 50, 50, 60, 60)]
    result = match_boxes(a, b)
    assert (result.only_a, result.only_b) == (0, 1)


def test_the_closest_pairs_win_not_the_first_ones() -> None:
    a = [box("a", 0, 0, 10, 10), box("a", 100, 100, 110, 110)]
    b = [box("a", 100, 100, 110, 111), box("a", 0, 0, 10, 10)]
    result = match_boxes(a, b)
    assert sorted(result.deviations) == [0.0, 1.0]


def test_boxes_of_different_labels_never_match() -> None:
    result = match_boxes([box("a", 0, 0, 5, 5)], [box("b", 0, 0, 5, 5)])
    assert (result.only_a, result.only_b, result.deviations) == (1, 1, ())


def test_empty_sets_match_trivially() -> None:
    assert match_boxes([], []).max_deviation == 0.0


def test_the_deviation_is_the_largest_coordinate_difference() -> None:
    result = match_boxes([box("a", 0, 0, 10, 10)], [box("a", 1, 0, 10, 13)])
    assert result.max_deviation == 3.0


# ----------------------------------------------------------------------------- box_in_bounds


def test_bounds_allow_a_small_tolerance_and_reject_degenerate_boxes() -> None:
    assert box_in_bounds(box("a", 0, 0, 100, 50), 100, 50)
    assert box_in_bounds(box("a", -0.4, 0, 100.4, 50), 100, 50)
    assert not box_in_bounds(box("a", -2, 0, 50, 50), 100, 50)
    assert not box_in_bounds(box("a", 10, 10, 10, 20), 100, 50)  # zero width
    assert not box_in_bounds(box("a", 222.7, 0.0, 300.0, 0.0), 300, 300)  # zero height
    assert not box_in_bounds(box("a", 0, 0, 101, 50), 100, 50)


# -------------------------------------------------------------------------- similarity tests


def noise(seed: int, length: int = 64) -> bytes:
    rng = random.Random(seed)
    return bytes(rng.randrange(256) for _ in range(length))


def perturbed(base: bytes, seed: int) -> bytes:
    rng = random.Random(seed)
    return bytes(max(0, min(255, b + rng.randrange(-8, 9))) for b in base)


def test_nearest_neighbour_test_finds_groups_of_similar_images() -> None:
    bases = [noise(1), noise(2), noise(3)]
    thumbs, groups = [], []
    for g, base in enumerate(bases):
        for i in range(4):
            thumbs.append(perturbed(base, 100 * g + i))
            groups.append(f"g{g}")
    result = nearest_neighbour_test(thumbs, groups)
    assert result.n == 12
    assert result.hits == 12
    assert result.rate == 1.0
    assert 0 < result.chance < 0.5


def test_nearest_neighbour_test_is_near_chance_for_unrelated_groups() -> None:
    thumbs = [noise(i) for i in range(30)]
    groups = [f"g{i % 3}" for i in range(30)]
    result = nearest_neighbour_test(thumbs, groups)
    assert result.rate < 0.7


def test_locality_test_sees_a_sequence_whose_neighbours_are_alike() -> None:
    rng = random.Random(0)
    # blocks of nearly identical hashes, blocks unrelated to each other
    hashes: list[int] = []
    for _ in range(40):
        base = rng.getrandbits(64)
        hashes += [base ^ (1 << rng.randrange(64)) for _ in range(5)]
    result = locality_test(hashes)
    assert result.adjacent_median < result.random_median
    assert result.adjacent_close > result.random_close


def test_locality_test_sees_nothing_in_a_random_sequence() -> None:
    rng = random.Random(1)
    result = locality_test([rng.getrandbits(64) for _ in range(400)])
    assert abs(result.adjacent_median - result.random_median) < 6


# ----------------------------------------------------------------------------------- imaging


def test_a_good_image_is_described_completely(tmp_path: Path) -> None:
    path = tmp_path / "a.jpg"
    write_jpeg(path, 1, (40, 30))
    info = inspect_image(path, thumbnail=8)
    assert info.ok
    assert (info.width, info.height, info.format, info.mode) == (40, 30, "JPEG", "RGB")
    assert info.exif_orientation is None
    assert info.dhash is not None
    assert len(info.dhash) == 16
    assert info.thumbnail is not None
    assert len(info.thumbnail) == 64
    assert info.error is None


def test_the_dhash_is_deterministic_and_content_dependent(tmp_path: Path) -> None:
    one, two = tmp_path / "1.jpg", tmp_path / "2.jpg"
    write_jpeg(one, 1)
    write_jpeg(two, 2)
    assert inspect_image(one).dhash == inspect_image(one).dhash
    assert inspect_image(one).dhash != inspect_image(two).dhash


def test_dhash64_of_a_horizontal_gradient_is_all_ones_or_zeros() -> None:
    ramp_down = Image.new("L", (9, 8))
    ramp_down.putdata([255 - 28 * x for _ in range(8) for x in range(9)])
    assert dhash64(ramp_down) == "f" * 16
    ramp_up = Image.new("L", (9, 8))
    ramp_up.putdata([28 * x for _ in range(8) for x in range(9)])
    assert dhash64(ramp_up) == "0" * 16


def test_a_truncated_jpeg_is_reported_not_raised(tmp_path: Path) -> None:
    good = tmp_path / "good.jpg"
    write_jpeg(good, 3, (64, 64))
    data = good.read_bytes()
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(data[: len(data) // 2])
    info = inspect_image(bad)
    assert not info.ok
    assert info.error is not None


def test_garbage_and_empty_files_are_reported(tmp_path: Path) -> None:
    garbage = tmp_path / "g.jpg"
    garbage.write_bytes(b"this is not an image")
    empty = tmp_path / "e.jpg"
    empty.write_bytes(b"")
    assert not inspect_image(garbage).ok
    assert not inspect_image(empty).ok
    assert "UnidentifiedImageError" in (inspect_image(garbage).error or "")


def test_a_missing_file_is_reported(tmp_path: Path) -> None:
    info = inspect_image(tmp_path / "nope.jpg")
    assert not info.ok
    assert "FileNotFoundError" in (info.error or "")


def test_exif_orientation_is_read(tmp_path: Path) -> None:
    image = Image.new("RGB", (20, 10), "red")
    exif = Image.Exif()
    exif[0x0112] = 6
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", exif=exif.tobytes())
    path = tmp_path / "rotated.jpg"
    path.write_bytes(buffer.getvalue())
    assert inspect_image(path).exif_orientation == 6
