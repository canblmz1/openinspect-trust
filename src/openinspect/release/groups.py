"""Grouping constraints for the group-aware splits, and how many of them a split crosses.

Four kinds of constraint, each a set of release items that must share one split:

* ``metadata_group``: items with the same source key ``group_id`` (a production batch, a design
  family): proxy metadata declared per source in ``configs/dedup.yaml``;
* ``similarity_component``: items whose image lies in one M3 visual similarity component (a
  machine-detected potential leakage group) at the source's primary level, the chaining rule of
  the M3 protocol; components may span sources;
* ``exact_duplicate``: items with the same file SHA-256;
* ``crop_parent``: crops of one original image.

The union of all constraints gives the groups that a group-aware split assigns whole.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import pyarrow.parquet as pq

from openinspect.release.pool import Candidate

KINDS = ("metadata_group", "similarity_component", "exact_duplicate", "crop_parent")


@dataclass(frozen=True)
class Constraint:
    kind: str
    key: str
    members: tuple[int, ...]  # indices into the release items


def read_components(path: Path, primary: Mapping[str, str]) -> dict[tuple[str, str], str]:
    """(source, image) -> component id, from ``leakage-groups.parquet`` at each source's level.

    ``primary`` maps a source to its primary level (``near`` or ``family``). A component at a
    level keeps only the members whose source uses that level, so a chained source contributes its
    near-level components and the others their family-level ones.
    """
    table = pq.read_table(path, columns=["group_id", "level", "members"]).to_pylist()
    found: dict[tuple[str, str], str] = {}
    for row in table:
        for member in row["members"]:
            source, _, image = str(member).partition(":")
            if primary.get(source) == row["level"]:
                found[(source, image)] = str(row["group_id"])
    return found


def constraints(
    items: Sequence[Candidate],
    components: Mapping[tuple[str, str], str],
    sha256: Sequence[str],
) -> list[Constraint]:
    """Every constraint with at least two members, in a fixed order."""
    found: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, item in enumerate(items):
        image = item.item
        if image.group_id is not None:
            found[("metadata_group", f"{image.source}:{image.group_id}")].append(index)
        component = components.get(image.key)
        if component is not None:
            found[("similarity_component", component)].append(index)
        found[("exact_duplicate", sha256[index])].append(index)
        if item.crop is not None:
            found[("crop_parent", f"{image.source}:{image.item_id}")].append(index)
    return [
        Constraint(kind, key, tuple(members))
        for (kind, key), members in sorted(
            found.items(), key=lambda kv: (KINDS.index(kv[0][0]), kv[0][1])
        )
        if len(members) > 1
    ]


def union_groups(n: int, found: Sequence[Constraint]) -> list[int]:
    """The group of every item: the smallest item index of its connected set."""
    parent = list(range(n))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for c in found:
        first = root(c.members[0])
        for member in c.members[1:]:
            other = root(member)
            if other != first:
                low, high = min(first, other), max(first, other)
                parent[high] = low
                first = low
    return [root(i) for i in range(n)]


def group_keys(items: Sequence[Candidate], groups: Sequence[int]) -> list[str]:
    """The key of every item's group: the smallest global id in it (independent of item order)."""
    smallest: dict[int, str] = {}
    for item, group in zip(items, groups, strict=True):
        if group not in smallest or item.global_id < smallest[group]:
            smallest[group] = item.global_id
    return [smallest[group] for group in groups]


def crossing(found: Sequence[Constraint], split_of: Sequence[str | None]) -> dict[str, int]:
    """Per kind: constraints whose members lie in more than one split (unassigned items ignored)."""
    counts = dict.fromkeys(KINDS, 0)
    for c in found:
        splits = {split_of[i] for i in c.members if split_of[i] is not None}
        if len(splits) > 1:
            counts[c.kind] += 1
    return counts
