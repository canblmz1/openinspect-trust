"""Group-aware and source-held-out assignments for measurement (M3G); not the release splits (M5).

Two different guarantees, kept apart on purpose:

* ``group_aware_split`` assigns whole groups to splits so that the image counts follow the wanted
  ratios as closely as the group sizes allow. It guarantees **group integrity** (no group is cut
  by a split boundary) and nothing else: it does not know which source an item comes from, so a
  source's items can land in every split.
* ``leave_one_source_out`` guarantees **source integrity**: every item of the held-out source is
  in ``test`` and no other item is.

M3 uses the first to measure what a split without similarity groups across its boundary would
look like; the source-held-out evaluation (split B) is built from the second.
"""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Mapping, Sequence


class SplitError(Exception):
    """A split cannot be built as asked."""


def group_aware_split(
    group_of: Sequence[int],
    ratios: Mapping[str, float],
    *,
    seed: int = 0,
) -> list[str]:
    """Split name for every item; all items of a group get the same split (group integrity only).

    ``group_of[i]`` is the group id of item ``i`` (singletons are groups of one). Groups are placed
    largest first into the split with the largest remaining deficit, ties broken by a seeded shuffle,
    so the result is a pure function of the inputs. Sources are not an input: to keep a source
    whole, use :func:`leave_one_source_out` (or make the source part of the group id).
    """
    if not ratios or any(r <= 0 for r in ratios.values()):
        raise SplitError("ratios must be positive")
    total_ratio = sum(ratios.values())
    n = len(group_of)
    members: dict[int, list[int]] = defaultdict(list)
    for index, group in enumerate(group_of):
        members[group].append(index)
    names = list(ratios)
    targets = {name: n * ratios[name] / total_ratio for name in names}
    filled = dict.fromkeys(names, 0)
    rng = random.Random(f"split:{seed}")  # noqa: S311 - reproducible shuffling, not cryptography
    order = sorted(members, key=lambda g: (-len(members[g]), rng.random(), g))
    result = [""] * n
    for group in order:
        best = max(names, key=lambda name: (targets[name] - filled[name], -names.index(name)))
        for index in members[group]:
            result[index] = best
        filled[best] += len(members[group])
    return result


def groups_crossing(group_of: Sequence[int], split_of: Sequence[str | None]) -> int:
    """Number of groups whose members do not all share one (known) split."""
    seen: dict[int, set[str]] = defaultdict(set)
    for group, split in zip(group_of, split_of, strict=True):
        if split is not None:
            seen[group].add(split)
    return sum(1 for splits in seen.values() if len(splits) > 1)


def leave_one_source_out(sources: Sequence[str], held_out: str) -> list[str]:
    """``test`` for the held-out source, ``train`` for every other source: no source is ever split."""
    if held_out not in set(sources):
        raise SplitError(f"{held_out!r} is not one of the sources")
    return ["test" if source == held_out else "train" for source in sources]
