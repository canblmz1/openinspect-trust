"""Release assembly: ids, crops, quotas, sample, constraints, splits, measurements, invariants."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest
import yaml
from PIL import Image

from openinspect.release.checks import ImagePair, invariants, measure, primary_pair
from openinspect.release.config import (
    RELEASE_PATH,
    CropPolicy,
    ReleaseConfigError,
    SizeRange,
    load_release_config,
)
from openinspect.release.crops import crop_png, crop_rect, open_image, plan_crops, shift
from openinspect.release.groups import constraints, crossing, group_keys, union_groups
from openinspect.release.ids import ID_PATTERN, IdCollisionError, check_unique, global_id
from openinspect.release.pool import (
    ReleaseError,
    build_candidates,
    largest_remainder,
    quotas,
    sample,
)
from openinspect.release.splits import (
    EXCLUDED,
    group_split,
    held_out_split,
    linked_to,
    random_split,
)
from openinspect.taxonomy.config import Taxonomy
from openinspect.taxonomy.mapping import AnnotatedImage, map_images
from tests.dedup_helpers import REPO_ROOT
from tests.release_helpers import RELEASE, TAXONOMY, candidate, mbox
from tests.taxonomy_helpers import box, item

POLICY = CropPolicy(min_side_px=100, margin=0.1)


def test_global_ids_are_stable_and_content_defined() -> None:
    a = global_id("pcb-ind", "ab" * 32)
    assert a == global_id("pcb-ind", "ab" * 32)
    assert ID_PATTERN.match(a)
    assert a != global_id("pcb-ind", "ab" * 32, (0, 0, 10, 10))
    assert a != global_id("dspcbsd-plus", "ab" * 32)
    check_unique([a, global_id("pcb-ind", "cd" * 32)])
    with pytest.raises(IdCollisionError):
        check_unique([a, a])


def test_the_committed_release_config() -> None:
    config = load_release_config(REPO_ROOT)
    assert config.max_source_share == pytest.approx(0.4)
    assert config.crops["pcb-defect"].min_side_px == 300
    assert config.smoke.counts == {"train": 10, "val": 5, "test": 5}


def test_release_config_errors(tmp_path: Path) -> None:
    with pytest.raises(ReleaseConfigError, match="cannot read"):
        load_release_config(tmp_path)
    path = tmp_path / RELEASE_PATH
    path.parent.mkdir(parents=True)
    for change in (
        {"size": {"min": 9, "max": 3}},
        {"splits": {"ratios": {"val": 0.5, "train": 0.5}, "held_out_val": 0.2}},
        {"splits": {"ratios": {"val": 0.2, "test": 0.0, "train": 0.8}, "held_out_val": 0.2}},
        {"smoke": {"counts": {"train": 1, "val": 0, "test": 1}}},
    ):
        path.write_text(yaml.safe_dump({**RELEASE, **change}), encoding="utf-8")
        with pytest.raises(ReleaseConfigError, match="invalid"):
            load_release_config(tmp_path)
    shuffled = {
        **RELEASE,
        "splits": {**RELEASE["splits"], "ratios": {"test": 0.2, "val": 0.2, "train": 0.6}},
    }
    path.write_text(yaml.safe_dump(shuffled), encoding="utf-8")
    assert tuple(load_release_config(tmp_path).splits.ratios) == ("train", "val", "test")


def test_crop_rect_is_native_square_inside_the_image() -> None:
    assert crop_rect((10, 10, 30, 30), 400, 300, POLICY) == (0, 0, 100, 100)
    assert crop_rect((380, 280, 395, 295), 400, 300, POLICY) == (300, 200, 400, 300)
    big = crop_rect((100, 100, 260, 140), 400, 300, POLICY)  # 160 px box -> side 200
    assert big is not None
    assert big[2] - big[0] == 200
    assert crop_rect((0, 0, 290, 20), 400, 300, POLICY) is None  # 363 px side does not fit


def test_plan_crops_records_every_anchor() -> None:
    boxes = [
        mbox(0, "short", (20, 20, 40, 40)),  # crop (0, 0, 100, 100)
        mbox(1, "open", (60, 60, 80, 80)),  # inside crop 0: covered
        mbox(2, "open", (120, 20, 140, 40)),  # crop (80, 0, 180, 100) overlaps crop 0
        mbox(3, "short", (300, 300, 320, 320)),  # its crop cuts box 4
        mbox(4, "open", (330, 330, 420, 420)),
        mbox(5, "short", (300, 20, 320, 40)),  # its crop holds a box of another class
        mbox(6, "spur", (330, 30, 340, 40), benchmark=False),
        mbox(7, "short", (5, 400, 5, 420)),  # zero width
        mbox(8, "open", (100, 440, 160, 470)),  # fine: crop (80, 405, 180, 505)
    ]
    outcome = plan_crops(500, 500, boxes, POLICY)
    assert [(p.anchor, p.rect, p.boxes) for p in outcome.plans] == [
        (0, (0, 0, 100, 100), (0, 1)),
        (8, (80, 400, 180, 500), (8,)),
    ]
    assert outcome.covered == (1,)
    assert dict(outcome.rejected) == {
        2: "overlaps_crop",
        3: "cuts_box",  # its 100 px crop cuts box 4
        4: "cuts_box",  # its 113 px crop cuts box 3
        5: "other_class_inside",
        7: "invalid_box",
    }
    assert shift((20, 20, 40, 40), (10, 5, 110, 105)) == (10, 15, 30, 35)


def test_plan_crops_rejects_cut_boxes_large_boxes_and_unknown_positions() -> None:
    cut = plan_crops(
        400, 400, [mbox(0, "short", (50, 50, 60, 60)), mbox(1, "open", (90, 40, 140, 70))], POLICY
    )
    assert dict(cut.rejected) == {0: "cuts_box"}
    assert [p.anchor for p in cut.plans] == [1]
    large = plan_crops(200, 200, [mbox(0, "short", (0, 0, 190, 20))], POLICY)
    assert dict(large.rejected) == {0: "too_large"}
    nan = plan_crops(
        400,
        400,
        [mbox(0, "short", (10, 10, 20, 20)), mbox(1, "open", (float("nan"), 0, 1, 1))],
        POLICY,
    )
    assert dict(nan.rejected) == {0: "invalid_box", 1: "invalid_box"}


def test_crop_png_is_lossless_and_hashes_pixels(tmp_path: Path) -> None:
    path = tmp_path / "p.png"
    Image.new("RGB", (50, 40), (10, 20, 30)).save(path)
    image = open_image(path)
    data, pixels = crop_png(image, (5, 5, 25, 25))
    again, pixels_again = crop_png(image, (5, 5, 25, 25))
    assert data == again
    assert pixels == pixels_again
    assert len(pixels) == 64


def _taxonomy() -> Taxonomy:
    return Taxonomy.model_validate(TAXONOMY)


def test_build_candidates_excludes_with_reasons() -> None:
    from openinspect.release.config import ReleaseConfig

    config = ReleaseConfig.model_validate(RELEASE)
    images = [
        AnnotatedImage(item("src-a", "ok.png"), (box(0, "SH", (1, 1, 9, 9)),)),
        AnnotatedImage(item("src-a", "spur.png"), (box(0, "SP", (1, 1, 9, 9)),)),
        AnnotatedImage(item("src-a", "bad.png"), (box(0, "SH", (1, 1, 9, 9), in_bounds=False),)),
        AnnotatedImage(item("src-b", "empty.png"), ()),
        AnnotatedImage(item("src-b", "nosize.png", size=(0, 0)), (box(0, "short", (1, 1, 9, 9)),)),
        AnnotatedImage(
            item("src-c", "big.png", size=(300, 300)), (box(0, "short", (10, 10, 30, 30)),)
        ),
        AnnotatedImage(
            item("src-c", "none.png", size=(300, 300)), (box(0, "spur", (10, 10, 30, 30)),)
        ),
        AnnotatedImage(item("src-c", "tiny.png", size=(0, 0)), (box(0, "short", (1, 1, 2, 2)),)),
    ]
    candidates, excluded = build_candidates(map_images(images, _taxonomy()), _taxonomy(), config)
    assert [(c.source, c.item.item_id, c.crop) for c in candidates] == [
        ("src-a", "ok.png", None),
        ("src-c", "big.png", (0, 0, 100, 100)),
    ]
    assert candidates[1].file_name.endswith(".png")
    assert candidates[0].boxes[0].class_id == 0
    reasons = {(e.source_item_id, e.reason) for e in excluded}
    assert reasons == {
        ("spur.png", "non_benchmark_class"),
        ("bad.png", "invalid_box"),
        ("empty.png", "no_boxes"),
        ("nosize.png", "unknown_size"),
        ("big.png", "replaced_by_crops"),
        ("none.png", "no_crop"),
        ("tiny.png", "unknown_size"),
    }
    included = ReleaseConfig.model_validate({**RELEASE, "negatives": "include"})
    with_negatives, _ = build_candidates(map_images(images, _taxonomy()), _taxonomy(), included)
    assert ("src-b", "empty.png") in {(c.source, c.item.item_id) for c in with_negatives}


def test_largest_remainder_and_quotas() -> None:
    assert largest_remainder({"a": 1.0, "b": 1.0, "c": 1.0}, 10) == {"a": 4, "b": 3, "c": 3}
    assert largest_remainder({"a": 0.0}, 3) == {"a": 0}
    size = SizeRange(min=10, max=5000)
    assert quotas({"big": 3292, "mid": 1713, "crop": 939}, 0.4, size) == {
        "big": 1768,
        "mid": 1713,
        "crop": 939,
    }
    assert (
        sum(quotas({"a": 3000, "b": 3000, "c": 3000}, 0.4, SizeRange(min=10, max=600)).values())
        == 600
    )
    with pytest.raises(ReleaseError, match="only"):
        quotas({"a": 100, "b": 1}, 0.4, size)


def test_sample_is_seeded_and_stratified() -> None:
    pool = [candidate("s", f"x{k}", ("short",) if k < 30 else ("open",)) for k in range(40)]
    first, dropped = sample(pool, {"s": 20}, seed=0)
    again, _ = sample(list(reversed(pool)), {"s": 20}, seed=0)
    assert [c.global_id for c in first] == [c.global_id for c in again]
    assert Counter(c.signature for c in first) == Counter({"short": 15, "open": 5})
    assert len(dropped) == 20
    assert {d.reason for d in dropped} == {"not_sampled"}
    other, _ = sample(pool, {"s": 20}, seed=1)
    assert {c.global_id for c in other} != {c.global_id for c in first}
    everything, none = sample(pool, {"s": 99}, seed=0)
    assert len(everything) == 40
    assert none == []


def test_constraints_union_and_crossing() -> None:
    items = [
        candidate("b", "b0", group="B0"),
        candidate("b", "b1", group="B0"),
        candidate("a", "a0"),
        candidate("c", "c0", crop=(0, 0, 10, 10)),
        candidate("c", "c0", crop=(20, 0, 30, 10)),
        candidate("a", "a1", sha="f" * 64),
        candidate("a", "a2", sha="f" * 64),
    ]
    sha = [i.item.sha256 for i in items]
    found = constraints(items, {("a", "a0"): "VSG-1", ("b", "b1"): "VSG-1"}, sha)
    kinds = Counter(c.kind for c in found)
    assert kinds == Counter(
        {"metadata_group": 1, "similarity_component": 1, "crop_parent": 1, "exact_duplicate": 2}
    )
    groups = union_groups(len(items), found)
    assert groups[0] == groups[1] == groups[2]
    assert groups[3] == groups[4]
    keys = group_keys(items, groups)
    assert keys[0] == min(items[0].global_id, items[1].global_id, items[2].global_id)
    split = ["train", "test", "train", "val", "val", "train", "train"]
    assert crossing(found, split) == {
        "metadata_group": 1,
        "similarity_component": 1,
        "exact_duplicate": 0,
        "crop_parent": 0,
    }


def test_random_split_is_stratified_and_order_free() -> None:
    items = [candidate("s", f"x{k}", ("short",) if k % 4 else ("open",)) for k in range(100)]
    ratios = {"train": 0.7, "val": 0.2, "test": 0.1}
    split = random_split(items, ratios, 0)
    counts = Counter(split)
    assert abs(counts["train"] - 70) <= 2
    assert abs(counts["val"] - 20) <= 1
    assert abs(counts["test"] - 10) <= 2
    for label in ("short", "open"):
        stratum = [s for i, s in zip(items, split, strict=True) if i.signature == label]
        assert abs(stratum.count("train") / len(stratum) - 0.7) < 0.03
    reverse = random_split(items[::-1], ratios, 0)[::-1]
    assert reverse == split


def test_group_split_keeps_groups_whole_and_balances() -> None:
    items = [candidate("s", f"x{k}", group=f"G{k // 4}") for k in range(80)]
    items += [candidate("t", f"y{k}", ("short",) if k % 3 else ("open",)) for k in range(40)]
    found = constraints(items, {}, [i.item.sha256 for i in items])
    keys = group_keys(items, union_groups(len(items), found))
    split = group_split(items, keys, {"train": 0.7, "val": 0.2, "test": 0.1}, 0)
    assert crossing(found, split)["metadata_group"] == 0
    assert Counter(s for i, s in zip(items, split, strict=True) if i.source == "s") == Counter(
        {"train": 56, "val": 16, "test": 8}
    )
    assert Counter(s for i, s in zip(items, split, strict=True) if i.source == "t") == Counter(
        {"train": 28, "val": 8, "test": 4}
    )
    eligible = [i.source == "t" for i in items]
    partial = group_split(items, keys, {"train": 0.5, "val": 0.5}, 0, eligible=eligible)
    assert partial[:80] == [None] * 80
    assert set(partial[80:]) == {"train", "val"}


def test_held_out_split_excludes_items_linked_to_the_test_source() -> None:
    items = [candidate("a", f"a{k}", group=f"A{k // 2}") for k in range(8)]
    items += [candidate("b", f"b{k}") for k in range(4)]
    components = {("a", "a0"): "VSG-x", ("b", "b0"): "VSG-x"}
    found = constraints(items, components, [i.item.sha256 for i in items])
    keys = group_keys(items, union_groups(len(items), found))
    assert linked_to(items, found, "b") == {0}
    split = held_out_split(items, keys, found, "b", 0.25, 0)
    assert split[:8].count(EXCLUDED) == 1  # only a0, not its batch mate a1
    assert split[0] == EXCLUDED
    assert set(split[8:]) == {"test"}
    assert set(split[1:8]) <= {"train", "val"}


def test_measure_and_primary_pairs() -> None:
    items = [
        candidate("a", "a0", sha="1" * 64),
        candidate("a", "a1", sha="1" * 64),
        candidate("c", "c0", crop=(0, 0, 9, 9)),
    ]
    pairs = [
        ImagePair("a", "a0", "a", "a1", "NEAR_DUPLICATE"),
        ImagePair("a", "a0", "c", "c0", "SAME_FAMILY_OR_SCENE"),
        ImagePair("a", "a0", "x", "gone", "NEAR_DUPLICATE"),
    ]
    primary = {"a": "family", "c": "near"}
    assert primary_pair(pairs[0], primary)
    assert not primary_pair(pairs[1], primary)
    assert primary_pair(ImagePair("a", "a0", "a", "a1", "SAME_FAMILY_OR_SCENE"), primary)
    sha = [i.item.sha256 for i in items]
    m = measure(items, ["train", "test", EXCLUDED], [], pairs, primary, sha)
    assert m.images == {"excluded": {"c": 1}, "test": {"a": 1}, "train": {"a": 1}}
    assert m.pairs_crossing == {"NEAR_DUPLICATE": 1}
    assert m.pairs_train_test == {"NEAR_DUPLICATE": 1}
    assert m.primary_pairs_crossing == 1
    assert m.sha256_crossing == 1  # a0 and a1 have the same bytes and different splits
    assert m.shares == {"test": 0.5, "train": 0.5}
    assert m.supplied_groups_crossing == 0


def test_invariants_pass_and_fail() -> None:
    from openinspect.release.checks import Provenance

    items = [candidate("a", "a0", sha="1" * 64), candidate("b", "b0", sha="2" * 64)]
    schemes = {"A0": ["train", "test"], "A1": ["train", "test"], "B-b": ["train", "test"]}
    measures = {n: measure(items, s, [], [], {}, ["1" * 64, "2" * 64]) for n, s in schemes.items()}
    prov = [Provenance(i.source, i.item.item_id, "https://x", "CC-BY-4.0", "a" * 64) for i in items]
    ok = invariants(
        items,
        schemes,
        measures,
        prov,
        allowlist={"CC-BY-4.0"},
        benchmark={"short", "open"},
        rebuild=lambda: schemes,
    )
    assert {i.id: i.status for i in ok} == {f"I{k}": "PASS" for k in range(1, 10)}
    bad_prov = [Provenance("a", "a0", "", "GPL", "a" * 64), prov[1]]
    bad = invariants(
        items,
        {**schemes, "B-a": ["test", "test"]},
        measures,
        bad_prov,
        allowlist={"CC-BY-4.0"},
        benchmark={"open"},
        rebuild=lambda: {},
    )
    status = {i.id: i.status for i in bad}
    assert status["I1"] == "FAIL"  # B-a tests on b as well
    assert status["I6"] == "FAIL"
    assert status["I7"] == "FAIL"
    assert status["I8"] == "FAIL"
    assert status["I9"] == "FAIL"
