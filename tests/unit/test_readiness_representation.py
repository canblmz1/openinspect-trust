from __future__ import annotations

from pathlib import Path
from typing import cast

from openinspect.readiness.release_view import ReleaseView
from openinspect.readiness.representation import (
    MATERIAL_CHANGED_SHARE,
    analyse,
    constraints_with,
    pairs_crossing,
    pairs_train_test,
)
from openinspect.release.config import ReleaseConfig
from openinspect.release.manifest import ReleaseManifest
from openinspect.release.splits import EXCLUDED, group_split
from tests.readiness_helpers import candidate

CONFIG = ReleaseConfig.model_validate(
    {
        "schema_version": 1,
        "version": "v0.1",
        "seed": 0,
        "size": {"min": 1, "max": 10000},
        "max_source_share": 1.0,
        "splits": {"ratios": {"train": 0.7, "val": 0.2, "test": 0.1}, "held_out_val": 0.15},
        "smoke": {"counts": {"train": 1, "val": 1, "test": 1}},
    }
)


def view() -> ReleaseView:
    items = []
    for source in ("a", "b"):
        for k in range(40):
            items.append(
                candidate(
                    f"OI_{source}_{k:02d}",
                    source,
                    ("short",) if k % 2 else ("open",),
                    item_id=f"{source}{k}.jpg",
                )
            )
    # small: chains of ten images per source, plus one component linking the two sources
    small = {
        (i.source, i.item.item_id): f"S-{i.source}-{int(i.global_id[-2:]) // 10}" for i in items
    }
    small[("b", "b0.jpg")] = "S-a-0"
    sha = [f"{k:064x}" for k in range(len(items))]
    found, keys = constraints_with(
        cast(ReleaseView, type("V", (), {"items": items, "sha256": sha})()), small
    )
    a1 = [s or EXCLUDED for s in group_split(items, keys, CONFIG.splits.ratios, 0)]
    return ReleaseView(
        root=Path("."),
        config=CONFIG,
        manifest=cast(ReleaseManifest, None),
        rows=[],
        items=items,
        sha256=sha,
        primary={"a": "family", "b": "family"},
        components=small,
        constraints=found,
        groups=keys,
        schemes={"A1": a1},
        pairs=[],
    )


def test_a_finer_grouping_changes_the_split_and_is_reported_as_material() -> None:
    v = view()
    # base: each small chain split in two by parity, and no link across sources
    base = {
        key: f"B-{key[0]}-{int(key[1][1:-4]) // 10}-{int(key[1][1:-4]) % 2}" for key in v.components
    }
    result, keys, a1_base = analyse(
        v,
        base,
        base_primary={"a": "family", "b": "family"},
        small_model="small",
        base_model="base",
        small_thresholds={"family": 0.9, "near": 0.93},
        base_thresholds={"family": 0.95, "near": 0.95},
        base_pairs=[("a", "a0.jpg", "a", "a2.jpg")],
        designs={"C1-d0": v.schemes["A1"]},
    )
    assert len(keys) == len(a1_base) == len(v.items)
    assert result.changed_items == sum(
        1 for x, y in zip(v.schemes["A1"], a1_base, strict=True) if x != y
    )
    assert result.changed_share == round(result.changed_items / len(v.items), 6)
    assert result.material == bool(result.material_reasons)
    if result.changed_share >= MATERIAL_CHANGED_SHARE:
        assert any("change split" in r for r in result.material_reasons)
    by_source = {m.source: m for m in result.membership}
    assert by_source["a"].components_small >= 1
    assert by_source["a"].in_component_base <= by_source["a"].items
    # the cross-source link exists under small only: B-strict excludes items under small, none under base
    held = {h.fold: h for h in result.held_out}
    assert held["B-a"].excluded_small > 0
    assert held["B-a"].excluded_base == 0
    assert (
        result.a1_base_pairs_crossing_base == 0
    )  # base pairs never cross a split built from base groups
    assert set(result.designs_base_pairs_train_test) == {"C1-d0"}


def test_pairs_crossing_counts_image_pairs_in_two_splits() -> None:
    v = view()
    split = ["train"] * len(v.items)
    split[1] = "test"
    pairs = [
        ("a", "a0.jpg", "a", "a1.jpg"),
        ("a", "a0.jpg", "a", "a2.jpg"),
        ("a", "zz.jpg", "a", "a0.jpg"),
    ]
    assert pairs_crossing(v, split, pairs) == 1


def test_pairs_train_test_counts_only_pairs_between_train_and_test() -> None:
    v = view()
    split = ["train"] * len(v.items)
    split[1], split[2], split[3] = "test", "val", "test"
    pairs = [
        ("a", "a1.jpg", "a", "a0.jpg"),  # test - train
        ("a", "a0.jpg", "a", "a3.jpg"),  # train - test
        ("a", "a0.jpg", "a", "a2.jpg"),  # train - val
        ("a", "a1.jpg", "a", "a3.jpg"),  # test - test
        ("a", "zz.jpg", "a", "a1.jpg"),  # not released
    ]
    assert pairs_train_test(v, split, pairs) == 2
