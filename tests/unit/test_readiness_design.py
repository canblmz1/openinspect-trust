from __future__ import annotations

from collections import Counter

import pytest

from openinspect.readiness.design import (
    DesignError,
    DesignParams,
    build_design,
    composition,
    exposed_test_items,
)
from openinspect.readiness.heldout import linked_training_items, natural_held_out_split, purity
from openinspect.release.splits import EXCLUDED
from tests.readiness_helpers import candidate, pool


def test_both_conditions_share_the_test_and_validation_sets_item_for_item() -> None:
    items, keys = pool()
    design = build_design(items, keys, DesignParams(seed=0))
    for name in ("test", "val"):
        assert [s == name for s in design.c0] == [s == name for s in design.c1]
    assert any(s == "test" for s in design.c0)
    assert any(s == "val" for s in design.c0)


def test_only_mates_and_replacements_differ_between_the_conditions() -> None:
    items, keys = pool()
    design = build_design(items, keys, DesignParams(seed=1))
    for role, a, b in zip(design.roles, design.c0, design.c1, strict=True):
        if role == "mate":
            assert (a, b) == ("train", EXCLUDED)
        elif role == "replacement":
            assert (a, b) == (EXCLUDED, "train")
        else:
            assert a == b


def test_c1_exposes_no_test_item_and_c0_exposes_exactly_the_probes() -> None:
    items, keys = pool()
    design = build_design(items, keys, DesignParams(seed=2))
    probes = {i for i, r in enumerate(design.roles) if r == "probe"}
    assert probes
    assert set(exposed_test_items(design.c0, keys)) == probes
    assert exposed_test_items(design.c1, keys) == []
    # no group of C1's training set touches a test or validation item
    held = {keys[i] for i, s in enumerate(design.c1) if s in ("test", "val")}
    assert not any(keys[i] in held for i, s in enumerate(design.c1) if s == "train")


def test_training_size_source_and_classes_are_matched() -> None:
    items, keys = pool()
    design = build_design(items, keys, DesignParams(seed=0))
    c0, c1 = composition(items, design.c0), composition(items, design.c1)
    assert c0.items["train"] == c1.items["train"]
    assert c0.signatures["train"] == c1.signatures["train"]
    assert c0.boxes["train"] == c1.boxes["train"]
    assert all(r.match == "profile" for r in design.replacements)
    assert Counter(design.roles)["mate"] == Counter(design.roles)["replacement"]


def test_large_groups_stay_whole_in_training() -> None:
    items, keys = pool()
    design = build_design(items, keys, DesignParams(seed=0, max_group=10))
    big = [i for i, k in enumerate(keys) if k.endswith(":big")]
    assert {design.roles[i] for i in big} <= {"core", "replacement"}


def test_the_design_is_a_pure_function_of_inputs_and_seed() -> None:
    items, keys = pool()
    first = build_design(items, keys, DesignParams(seed=3))
    again = build_design(items, keys, DesignParams(seed=3))
    other = build_design(items, keys, DesignParams(seed=4))
    assert first == again
    assert first.roles != other.roles


def test_a_source_without_spare_items_gets_closest_or_no_replacement() -> None:
    items = [
        candidate("OI_x_a", "x", ("short",)),
        candidate("OI_x_b", "x", ("short",)),
        candidate("OI_x_c", "x", ("open",)),
    ]
    keys = ["g", "g", "OI_x_c"]
    design = build_design(items, keys, DesignParams(seed=0, test_share=0.7, val_share=0.0))
    matches = [r.match for r in design.replacements]
    assert matches
    assert set(matches) <= {"closest", "none", "classes", "profile"}
    assert design.shortfalls["x"]["val"] == 0


def test_invalid_fractions_are_refused() -> None:
    items, keys = pool(2)
    with pytest.raises(DesignError, match="strictly between"):
        build_design(items, keys, DesignParams(exposed_fraction=1.0))


def test_shortfalls_are_reported_when_groups_are_missing() -> None:
    items = [candidate(f"OI_y_{k}", "y", ("short",)) for k in range(20)]
    keys = ["one"] * 20  # one group too large to split: nothing can be exposed or held out
    design = build_design(items, keys, DesignParams(seed=0, max_group=5))
    assert design.shortfalls["y"]["exposed"] > 0
    assert design.shortfalls["y"]["control"] > 0
    assert set(design.roles) == {"core"}


# --------------------------------------------------------------------------- held out


def test_b_natural_keeps_source_integrity_and_every_other_item() -> None:
    items, keys = pool()
    for source in ("src-a", "src-b", "src-c"):
        split = natural_held_out_split(items, keys, source, 0.15, 0)
        p = purity(items, split, source)
        assert p.ok
        assert p.excluded == 0
        assert p.test_sources == [source]
        assert {s for i, s in zip(items, split, strict=True) if i.source != source} <= {
            "train",
            "val",
        }


def test_purity_detects_a_mixed_held_out_split() -> None:
    items, keys = pool(2)
    split = natural_held_out_split(items, keys, "src-a", 0.15, 0)
    broken = ["test" if i == 0 and items[0].source != "src-a" else s for i, s in enumerate(split)]
    first_other = next(i for i, item in enumerate(items) if item.source != "src-a")
    broken[first_other] = "test"
    assert not purity(items, broken, "src-a").ok
    moved = list(split)
    moved[next(i for i, item in enumerate(items) if item.source == "src-a")] = "train"
    result = purity(items, moved, "src-a")
    assert result.held_out_items_outside_test == 1
    assert not result.ok


def test_linked_training_items_counts_groups_that_reach_the_test_set() -> None:
    keys = ["g1", "g1", "g2", "g3"]
    split = ["test", "train", "train", "val"]
    assert linked_training_items(split, keys) == 1


def test_every_probe_gets_the_strongest_link_to_its_mates() -> None:
    from openinspect.readiness.design import LINKS, probe_link_kinds, probe_links

    items = [
        candidate("OI_s_a", "s", item_id="x.jpg", group_id="batch1"),
        candidate("OI_s_b", "s", item_id="y.jpg", group_id="batch1"),
        candidate("OI_s_c", "s", item_id="z.jpg", group_id="batch1"),
        candidate("OI_s_d", "s", item_id="w.jpg", group_id="batch2"),
        candidate("OI_s_e", "s", item_id="v.jpg", group_id="batch3"),
    ]
    keys: list[str | None] = ["g1", "g1", "g1", "g2", "g2"]
    from openinspect.readiness.design import PairedDesign

    design = PairedDesign(
        params=DesignParams(),
        roles=["probe", "mate", "mate", "probe", "mate"],
        exposure_group=keys,
        c0=["test", "train", "train", "test", "train"],
        c1=["test", EXCLUDED, EXCLUDED, "test", EXCLUDED],
        replacements=[],
        shortfalls={},
    )
    similar = {frozenset({("s", "x.jpg"), ("s", "y.jpg")})}
    kinds = probe_link_kinds(items, design, {}, similar)
    assert kinds == ["similar pair", "", "", "transitive only", ""]
    assert probe_links(kinds) == {
        k: (1 if k in ("similar pair", "transitive only") else 0) for k in LINKS
    }
    no_pair = probe_link_kinds(items, design, {("s", "x.jpg"): "c", ("s", "z.jpg"): "c"}, set())
    assert no_pair[0] == "same component"
    metadata = probe_link_kinds(items, design, {}, set())
    assert metadata[0] == "same metadata group"
