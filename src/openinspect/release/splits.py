"""The three evaluation regimes: A0 (random), A1 (group-aware), B (source-held-out).

* **A0** assigns items at random within strata of (source, classes of the item), so every split
  gets the same source and class mix; groups are ignored on purpose: it is the naive benchmark.
* **A1** assigns whole groups (the union of every constraint in :mod:`openinspect.release.groups`)
  so that, per source and per class, the split shares follow the ratios as closely as the group
  sizes allow. Sources stay mixed. A group too large to move is placed whole, and the shares of
  its source show it.
* **B** holds one source out as the test set; the other sources are split into train and
  validation group-aware. A training-source item that shares a constraint with a held-out item
  (in practice a visual similarity component across sources) is excluded from that fold, so no
  constraint spans training and test.

Every function is a pure function of its inputs and the seed. What a split actually achieves
(crossing groups, crossing similar pairs, shares) is measured afterwards, never assumed.
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence

from openinspect.release.groups import Constraint
from openinspect.release.pool import Candidate, largest_remainder

EXCLUDED = "excluded"
CLASS_WEIGHT = 0.5  # per-source shares come first, the class mix second


def _order(seed: int, salt: str, value: str) -> str:
    return hashlib.sha256(f"{seed}:{salt}:{value}".encode()).hexdigest()


def random_split(items: Sequence[Candidate], ratios: Mapping[str, float], seed: int) -> list[str]:
    """A0: a seeded, stratified random split; every stratum is divided by largest remainder."""
    strata: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, item in enumerate(items):
        strata[(item.source, item.signature)].append(index)
    result = [""] * len(items)
    for _key, members in sorted(strata.items()):
        counts = largest_remainder(dict(ratios), len(members))
        ordered = sorted(members, key=lambda i: _order(seed, "A0", items[i].global_id))
        start = 0
        for split in ratios:
            for index in ordered[start : start + counts[split]]:
                result[index] = split
            start += counts[split]
    return result


def _keys(item: Candidate) -> list[tuple[str, str]]:
    keys = [("source", item.source)]
    keys += [("class", label) for label in sorted({b.normalized_label for b in item.boxes})]
    return keys


def group_split(
    items: Sequence[Candidate],
    groups: Sequence[str],
    ratios: Mapping[str, float],
    seed: int,
    *,
    eligible: Sequence[bool] | None = None,
) -> list[str | None]:
    """Whole groups to splits, balancing item counts per source and per class.

    ``groups[i]`` is the key of item i's group (for example its smallest global id), so the result
    does not depend on the order of ``items``. Groups are placed largest first (ties by a seeded
    hash of the key) into the split where the squared relative miss of the targets grows least;
    the targets are the item counts per source and, at half weight, per class. Items not
    ``eligible`` get ``None``.
    """
    use = list(eligible) if eligible is not None else [True] * len(items)
    total_ratio = sum(ratios.values())
    members: dict[str, list[int]] = defaultdict(list)
    for index, group in enumerate(groups):
        if use[index]:
            members[group].append(index)
    totals: Counter[tuple[str, str]] = Counter()
    vectors: dict[str, Counter[tuple[str, str]]] = {}
    for group, indices in members.items():
        vector: Counter[tuple[str, str]] = Counter()
        for index in indices:
            vector.update(_keys(items[index]))
        vectors[group] = vector
        totals.update(vector)
    names = list(ratios)
    filled: dict[str, Counter[tuple[str, str]]] = {name: Counter() for name in names}
    order = sorted(members, key=lambda g: (-len(members[g]), _order(seed, "groups", g), g))
    result: list[str | None] = [None] * len(items)
    for group in order:
        vector = vectors[group]

        def cost(name: str, vector: Counter[tuple[str, str]] = vector) -> tuple[float, int]:
            """How much the squared relative miss of the targets grows if the group goes here."""
            share = ratios[name] / total_ratio
            grow = sum(
                (1.0 if key[0] == "source" else CLASS_WEIGHT)
                * count
                * (2 * (filled[name][key] - share * totals[key]) + count)
                / totals[key] ** 2
                for key, count in vector.items()
            )
            return grow, names.index(name)

        best = min(names, key=cost)
        for index in members[group]:
            result[index] = best
        filled[best].update(vector)
    return result


def linked_to(
    items: Sequence[Candidate], constraints: Sequence[Constraint], source: str
) -> set[int]:
    """Items of other sources that share a constraint with an item of ``source``."""
    linked: set[int] = set()
    for c in constraints:
        if any(items[i].source == source for i in c.members):
            linked.update(i for i in c.members if items[i].source != source)
    return linked


def held_out_split(
    items: Sequence[Candidate],
    groups: Sequence[str],
    constraints: Sequence[Constraint],
    source: str,
    val_share: float,
    seed: int,
) -> list[str]:
    """B: ``test`` for the held-out source; train and val for the others; excluded when linked."""
    linked = linked_to(items, constraints, source)
    eligible = [item.source != source and i not in linked for i, item in enumerate(items)]
    inner = group_split(
        items, groups, {"train": 1 - val_share, "val": val_share}, seed, eligible=eligible
    )
    result: list[str] = []
    for index, item in enumerate(items):
        if item.source == source:
            result.append("test")
        elif not eligible[index]:
            result.append(EXCLUDED)
        else:
            result.append(inner[index] or EXCLUDED)
    return result
