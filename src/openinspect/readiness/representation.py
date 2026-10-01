"""How much the release's group-aware split depends on the embedding model (M5.5, P1-2).

A1 groups items by the visual similarity components of DINOv2-small (plus metadata keys,
identical files and crop parents). M3 found that DINOv2-base, calibrated by the same rule, groups
far fewer images. The question here is practical: would building the release's splits with the
base components change the actual training and evaluation population?

Everything is measured on the released items: membership in a component under each model, the
constraint groups that result, how the committed A1 cuts base-defined groups, what an A1 built
from base components (same algorithm, seed and targets) would look like, and how much
small-defined potential leakage such a split would contain.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence

import numpy as np
from pydantic import Field

from openinspect.dedup.metrics import PartitionAgreement, Quantiles, partition_agreement, quantiles
from openinspect.provenance.schema import StrictModel
from openinspect.readiness.release_view import ReleaseView
from openinspect.release.checks import measure
from openinspect.release.groups import Constraint, constraints, crossing, group_keys, union_groups
from openinspect.release.splits import EXCLUDED, group_split, linked_to

# Fixed before the base components were computed for the release (docs/DECISIONS.md, T40).
MATERIAL_CHANGED_SHARE = 0.10  # share of items whose A1 split differs
MATERIAL_SHARE_POINTS = 0.05  # change of a source's share of the test set
SPLITS = ("train", "val", "test")


class SourceMembership(StrictModel):
    source: str
    items: int
    in_component_small: int  # items in a multi-member visual similarity component
    in_component_base: int
    components_small: int
    components_base: int
    largest_small: int
    largest_base: int
    sizes_small: Quantiles | None
    sizes_base: Quantiles | None
    agreement: PartitionAgreement = Field(
        description="base components (predicted) against small components (reference), items with a component under either"
    )
    largest_group_small: int  # largest A1 constraint group
    largest_group_base: int


class SplitChange(StrictModel):
    source: str
    items: int
    changed: int
    a1: dict[str, int]
    a1_base: dict[str, int]


class HeldOutBase(StrictModel):
    fold: str
    excluded_small: int
    excluded_base: int


class RepresentationResult(StrictModel):
    small_model: str
    base_model: str
    small_thresholds: dict[str, float]
    base_thresholds: dict[str, float]
    small_primary: dict[str, str]
    base_primary: dict[str, str]
    membership: list[SourceMembership]
    a1_cuts_base: dict[str, int]  # base constraints crossing the committed A1, by kind
    a1_base_cuts_small: dict[str, int]  # small constraints crossing an A1 built from base
    a1_base_primary_pairs_crossing: int  # small primary-level M3 pairs across the base-built A1
    a1_base_pairs_train_test: dict[str, int]
    a1_base_pairs_crossing_base: int  # base similar pairs across the base-built A1
    a1_pairs_crossing_base: int  # base similar pairs across the committed A1
    designs_base_pairs_train_test: dict[str, int]  # C split -> base similar pairs train-test
    changed_items: int
    changed_share: float
    split_changes: list[SplitChange]
    test_share_shift: dict[str, float]  # source -> change of its share of the test set (points)
    split_presence: dict[str, dict[str, list[str]]]  # A1 / A1-base -> source -> splits present
    admissibility_changed_items: int  # items whose small constraint group the base-built A1 cuts
    held_out: list[HeldOutBase]
    material: bool
    material_reasons: list[str]


def release_components(
    view: ReleaseView, components: Mapping[tuple[str, str], str]
) -> list[str | None]:
    """The component of every released item (a crop inherits its parent's)."""
    return [components.get(item.item.key) for item in view.items]


def constraints_with(
    view: ReleaseView, components: Mapping[tuple[str, str], str]
) -> tuple[list[Constraint], list[str]]:
    found = constraints(view.items, components, view.sha256)
    return found, group_keys(view.items, union_groups(len(view.items), found))


def _sizes(labels: Sequence[str | None], idx: Sequence[int]) -> Counter[str]:
    return Counter(label for i in idx if (label := labels[i]) is not None)


def _codes(
    small: Sequence[str | None], base: Sequence[str | None], idx: Sequence[int]
) -> tuple[list[int], list[int]]:
    """Integer labels of the items under either component, singletons as their own label."""
    codes: dict[str, int] = {}
    pred: list[int] = []
    ref: list[int] = []
    for i in idx:
        if small[i] is None and base[i] is None:
            continue
        pred.append(codes.setdefault(f"b:{base[i]}" if base[i] else f"single:{i}", len(codes)))
        ref.append(codes.setdefault(f"s:{small[i]}" if small[i] else f"single:{i}", len(codes)))
    return pred, ref


def _membership(
    view: ReleaseView,
    small: Sequence[str | None],
    base: Sequence[str | None],
    keys_small: Sequence[str],
    keys_base: Sequence[str],
) -> list[SourceMembership]:
    out: list[SourceMembership] = []
    for source in sorted({item.source for item in view.items}):
        idx = [i for i, item in enumerate(view.items) if item.source == source]
        s_sizes, b_sizes = _sizes(small, idx), _sizes(base, idx)
        s_multi = {k for k, n in s_sizes.items() if n > 1}
        b_multi = {k for k, n in b_sizes.items() if n > 1}
        pred, ref = _codes(small, base, idx)
        out.append(
            SourceMembership(
                source=source,
                items=len(idx),
                in_component_small=sum(1 for i in idx if small[i] in s_multi),
                in_component_base=sum(1 for i in idx if base[i] in b_multi),
                components_small=len(s_multi),
                components_base=len(b_multi),
                largest_small=max((s_sizes[k] for k in s_multi), default=1),
                largest_base=max((b_sizes[k] for k in b_multi), default=1),
                sizes_small=quantiles(np.array([s_sizes[k] for k in s_multi], dtype=np.float64)),
                sizes_base=quantiles(np.array([b_sizes[k] for k in b_multi], dtype=np.float64)),
                agreement=partition_agreement(pred, ref),
                largest_group_small=max(Counter(keys_small[i] for i in idx).values()),
                largest_group_base=max(Counter(keys_base[i] for i in idx).values()),
            )
        )
    return out


def pairs_crossing(
    view: ReleaseView, split: Sequence[str], pairs: Sequence[tuple[str, str, str, str]]
) -> int:
    """Image pairs (source, image, source, image) whose released items lie in two splits."""
    by_image: dict[tuple[str, str], set[str]] = {}
    for item, name in zip(view.items, split, strict=True):
        if name != EXCLUDED:
            by_image.setdefault(item.item.key, set()).add(name)
    count = 0
    for sa, ia, sb, ib in pairs:
        a, b = by_image.get((sa, ia), set()), by_image.get((sb, ib), set())
        if a and b and not (len(a) == 1 and a == b):
            count += 1
    return count


def pairs_train_test(
    view: ReleaseView, split: Sequence[str], pairs: Sequence[tuple[str, str, str, str]]
) -> int:
    """Image pairs with one image in train and the other in test."""
    by_image: dict[tuple[str, str], set[str]] = {}
    for item, name in zip(view.items, split, strict=True):
        by_image.setdefault(item.item.key, set()).add(name)
    count = 0
    for sa, ia, sb, ib in pairs:
        a, b = by_image.get((sa, ia), set()), by_image.get((sb, ib), set())
        if ("train" in a and "test" in b) or ("test" in a and "train" in b):
            count += 1
    return count


def _shares(view: ReleaseView, split: Sequence[str], name: str) -> dict[str, float]:
    chosen = [item.source for item, s in zip(view.items, split, strict=True) if s == name]
    total = len(chosen) or 1
    counts = Counter(chosen)
    return {source: counts[source] / total for source in sorted({i.source for i in view.items})}


def analyse(
    view: ReleaseView,
    base_components: Mapping[tuple[str, str], str],
    *,
    base_primary: Mapping[str, str],
    small_model: str,
    base_model: str,
    small_thresholds: Mapping[str, float],
    base_thresholds: Mapping[str, float],
    base_pairs: Sequence[tuple[str, str, str, str]],
    designs: Mapping[str, Sequence[str]],
) -> tuple[RepresentationResult, list[str], list[str]]:
    """The comparison, the base constraint-group key of every item, and the base-built A1."""
    small = release_components(view, view.components)
    base = release_components(view, base_components)
    base_found, base_keys = constraints_with(view, base_components)
    a1 = view.schemes["A1"]
    ratios, seed = view.config.splits.ratios, view.config.seed
    a1_base = [s or EXCLUDED for s in group_split(view.items, base_keys, ratios, seed)]
    changed = [i for i, (x, y) in enumerate(zip(a1, a1_base, strict=True)) if x != y]
    measured = measure(view.items, a1_base, view.constraints, view.pairs, view.primary, view.sha256)
    splits_of: dict[str, set[str]] = {}
    for key, name in zip(view.groups, a1_base, strict=True):
        splits_of.setdefault(key, set()).add(name)
    cut_small_groups = {key for key, names in splits_of.items() if len(names) > 1}
    split_changes: list[SplitChange] = []
    for source in sorted({item.source for item in view.items}):
        idx = [i for i, item in enumerate(view.items) if item.source == source]
        split_changes.append(
            SplitChange(
                source=source,
                items=len(idx),
                changed=sum(1 for i in idx if a1[i] != a1_base[i]),
                a1={s: sum(1 for i in idx if a1[i] == s) for s in SPLITS},
                a1_base={s: sum(1 for i in idx if a1_base[i] == s) for s in SPLITS},
            )
        )
    before, after = _shares(view, a1, "test"), _shares(view, a1_base, "test")
    shift = {s: round(after[s] - before[s], 6) for s in before}
    presence = {
        name: {
            source: [
                s
                for s in SPLITS
                if any(
                    i.source == source and x == s for i, x in zip(view.items, split, strict=True)
                )
            ]
            for source in sorted({i.source for i in view.items})
        }
        for name, split in (("A1", a1), ("A1-base", a1_base))
    }
    held: list[HeldOutBase] = []
    for source in sorted({item.source for item in view.items}):
        held.append(
            HeldOutBase(
                fold=f"B-{source}",
                excluded_small=len(linked_to(view.items, view.constraints, source)),
                excluded_base=len(linked_to(view.items, base_found, source)),
            )
        )
    reasons: list[str] = []
    share = len(changed) / len(view.items)
    if share >= MATERIAL_CHANGED_SHARE:
        reasons.append(
            f"{share:.1%} of the items change split (threshold {MATERIAL_CHANGED_SHARE:.0%})"
        )
    for source in presence["A1"]:
        if presence["A1"][source] != presence["A1-base"][source]:
            reasons.append(
                f"`{source}` is in {'/'.join(presence['A1'][source])} under A1 and in "
                f"{'/'.join(presence['A1-base'][source])} under A1-base"
            )
    for source, delta in shift.items():
        if abs(delta) >= MATERIAL_SHARE_POINTS:
            reasons.append(f"`{source}` share of the test set moves by {100 * delta:+.1f} points")
    result = RepresentationResult(
        small_model=small_model,
        base_model=base_model,
        small_thresholds=dict(small_thresholds),
        base_thresholds=dict(base_thresholds),
        small_primary=dict(view.primary),
        base_primary=dict(base_primary),
        membership=_membership(view, small, base, view.groups, base_keys),
        a1_cuts_base=crossing(base_found, list(a1)),
        a1_base_cuts_small=crossing(view.constraints, list(a1_base)),
        a1_base_primary_pairs_crossing=measured.primary_pairs_crossing,
        a1_base_pairs_train_test=measured.pairs_train_test,
        a1_base_pairs_crossing_base=pairs_crossing(view, a1_base, base_pairs),
        a1_pairs_crossing_base=pairs_crossing(view, a1, base_pairs),
        designs_base_pairs_train_test={
            name: pairs_train_test(view, split, base_pairs)
            for name, split in sorted(designs.items())
        },
        changed_items=len(changed),
        changed_share=round(share, 6),
        split_changes=split_changes,
        test_share_shift=shift,
        split_presence=presence,
        admissibility_changed_items=sum(1 for k in view.groups if k in cut_small_groups),
        held_out=held,
        material=bool(reasons),
        material_reasons=reasons,
    )
    return result, base_keys, a1_base
