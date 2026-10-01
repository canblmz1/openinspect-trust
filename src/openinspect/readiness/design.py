"""A paired common-evaluation design: two training sets, one test set (M5.5, P1-1).

A0 and A1 differ in their test sets, in their test composition (A1 has no PCB-Defect test item)
and in their training sets, so A0 - A1 mixes leakage with a change of what is evaluated. The
design here holds the evaluation fixed and changes one factor of the training set:

* **C0** trains on a core set plus the *group-mates* of half of the test items (the other members
  of their A1 constraint groups: metadata keys, M3 visual similarity components, identical files,
  crops of one parent). Those test items are *exposed*.
* **C1** trains on the same core set plus *replacements*: as many items as there are mates, of the
  same source and the same set of classes, from groups that touch no test or validation item.

Both use the same test set (exposed *probes* plus unexposed *controls*) and the same validation
set; training size, source mix and class mix are equal by construction (measured afterwards).
C0 - C1 on the probes estimates the effect of training on group-mates of a test item; on the
controls it should be about zero, which makes them a negative control for the swap itself.

Every choice is a pure function of the release items, their constraint groups, the parameters and
the seed (hash-ordered), so the same inputs give the same design.
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from openinspect.release.pool import Candidate
from openinspect.release.splits import EXCLUDED

ROLES = ("probe", "control", "val", "core", "mate", "replacement")


class DesignError(Exception):
    """The design cannot be built with the given parameters."""


@dataclass(frozen=True)
class DesignParams:
    seed: int = 0
    test_share: float = 0.10  # of each source's released items, as in A0 and A1
    val_share: float = 0.20
    exposed_fraction: float = 0.5  # share of each source's test target that is exposed
    probe_fraction: float = 0.5  # share of an exposure group that goes to the test set
    max_group: int = 50  # groups larger than this stay whole in training


@dataclass(frozen=True)
class Replacement:
    mate: str  # global id of the mate it stands in for
    replacement: str | None
    match: str  # profile (same boxes per class), classes (same set), closest, none
    note: str = ""


@dataclass(frozen=True)
class PairedDesign:
    params: DesignParams
    roles: list[str]  # one of ROLES per item
    exposure_group: list[str | None]  # the constraint group of probes and mates
    c0: list[str]
    c1: list[str]
    replacements: list[Replacement]
    shortfalls: dict[str, dict[str, int]]  # source -> target name -> items missing


def _hash(*parts: object) -> str:
    return hashlib.sha256(":".join(str(p) for p in parts).encode("utf-8")).hexdigest()


def _probes(size: int, fraction: float) -> int:
    return max(1, int(size * fraction))


def _classes(item: Candidate) -> frozenset[str]:
    return frozenset(b.normalized_label for b in item.boxes)


def build_design(
    items: Sequence[Candidate], groups: Sequence[str], params: DesignParams
) -> PairedDesign:
    """C0 and C1 over ``items``; ``groups[i]`` is the A1 constraint-group key of item ``i``."""
    if not 0 < params.exposed_fraction < 1 or not 0 < params.probe_fraction < 1:
        raise DesignError("exposed_fraction and probe_fraction must lie strictly between 0 and 1")
    members: dict[str, list[int]] = defaultdict(list)
    for index, key in enumerate(groups):
        members[key].append(index)
    role: list[str] = ["core"] * len(items)
    exposure: list[str | None] = [None] * len(items)
    shortfalls: dict[str, dict[str, int]] = {}
    used: set[str] = set()
    for source in sorted({item.source for item in items}):
        n_source = sum(1 for item in items if item.source == source)
        test_target = round(params.test_share * n_source)
        val_target = round(params.val_share * n_source)
        exposed_target = round(params.exposed_fraction * test_target)
        control_target = test_target - exposed_target
        eligible = sorted(
            (
                key
                for key, idx in members.items()
                if len(idx) <= params.max_group and all(items[i].source == source for i in idx)
            ),
            key=lambda key: (_hash(params.seed, "design", key), key),
        )
        probes = controls = 0
        for key in eligible:
            size = len(members[key])
            exposed_gap = (exposed_target - probes) / max(exposed_target, 1)
            control_gap = (control_target - controls) / max(control_target, 1)
            if size >= 2 and exposed_gap > 0 and exposed_gap >= control_gap:
                ordered = sorted(
                    members[key],
                    key=lambda i: (_hash(params.seed, "probe", items[i].global_id), i),
                )
                cut = _probes(size, params.probe_fraction)
                for i in ordered[:cut]:
                    role[i] = "probe"
                for i in ordered[cut:]:
                    role[i] = "mate"
                for i in ordered:
                    exposure[i] = key
                probes += cut
                used.add(key)
            elif control_gap > 0:
                for i in members[key]:
                    role[i] = "control"
                controls += size
                used.add(key)
        val = 0
        for key in eligible:
            if val >= val_target:
                break
            if key in used:
                continue
            for i in members[key]:
                role[i] = "val"
            val += len(members[key])
            used.add(key)
        shortfalls[source] = {
            "exposed": max(0, exposed_target - probes),
            "control": max(0, control_target - controls),
            "val": max(0, val_target - val),
        }
    replacements = _replace(items, role, params.seed)
    by_id = {item.global_id: k for k, item in enumerate(items)}
    for r in replacements:
        if r.replacement is not None:
            role[by_id[r.replacement]] = "replacement"
    c0 = [_split(r, condition=0) for r in role]
    c1 = [_split(r, condition=1) for r in role]
    return PairedDesign(params, role, exposure, c0, c1, replacements, shortfalls)


def _split(role: str, *, condition: int) -> str:
    if role in ("probe", "control"):
        return "test"
    if role == "val":
        return "val"
    if role == "core":
        return "train"
    if role == "mate":
        return "train" if condition == 0 else EXCLUDED
    return "train" if condition == 1 else EXCLUDED  # replacement


def _profile(item: Candidate) -> tuple[tuple[str, int], ...]:
    """The boxes of an item per class: matching on it keeps the box counts equal too."""
    return tuple(sorted(Counter(b.normalized_label for b in item.boxes).items()))


def _replace(items: Sequence[Candidate], role: Sequence[str], seed: int) -> list[Replacement]:
    """A core item for every mate (seeded): the same source and the same boxes per class if any is
    left, else the same set of classes, else the closest set of classes."""
    pool: dict[str, list[int]] = defaultdict(list)
    for i, item in enumerate(items):
        if role[i] == "core":
            pool[item.source].append(i)
    for source in pool:
        pool[source].sort(key=lambda i: (_hash(seed, "replace", items[i].global_id), i))
    taken: set[int] = set()
    mates = sorted(
        (i for i, r in enumerate(role) if r == "mate"),
        key=lambda i: (
            items[i].source,
            items[i].signature,
            _hash(seed, "mate", items[i].global_id),
        ),
    )
    out: list[Replacement] = []
    for i in mates:
        candidates = [j for j in pool[items[i].source] if j not in taken]
        if not candidates:
            out.append(
                Replacement(items[i].global_id, None, "none", "no core item of this source is left")
            )
            continue
        profile, classes = _profile(items[i]), _classes(items[i])
        chosen = next((j for j in candidates if _profile(items[j]) == profile), None)
        match = "profile"
        if chosen is None:
            chosen = next((j for j in candidates if _classes(items[j]) == classes), None)
            match = "classes"
        if chosen is None:
            chosen = max(
                candidates,
                key=lambda j: (
                    len(classes & _classes(items[j])) / len(classes | _classes(items[j])),
                    -candidates.index(j),
                ),
            )
            match = "closest"
        taken.add(chosen)
        note = (
            ""
            if match == "profile"
            else f"{items[chosen].signature!r} ({len(items[chosen].boxes)} boxes) for "
            f"{items[i].signature!r} ({len(items[i].boxes)} boxes)"
        )
        out.append(Replacement(items[i].global_id, items[chosen].global_id, match, note))
    return out


@dataclass(frozen=True)
class Composition:
    items: dict[str, dict[str, int]]  # split -> source -> items
    signatures: dict[str, dict[str, int]]  # split -> class set -> items
    boxes: dict[str, dict[str, int]]  # split -> class -> boxes


def composition(items: Sequence[Candidate], split: Sequence[str]) -> Composition:
    by_source: dict[str, Counter[str]] = defaultdict(Counter)
    by_signature: dict[str, Counter[str]] = defaultdict(Counter)
    by_class: dict[str, Counter[str]] = defaultdict(Counter)
    for item, name in zip(items, split, strict=True):
        by_source[name][item.source] += 1
        by_signature[name][item.signature] += 1
        by_class[name].update(b.normalized_label for b in item.boxes)
    return Composition(
        items={k: dict(sorted(v.items())) for k, v in sorted(by_source.items())},
        signatures={k: dict(sorted(v.items())) for k, v in sorted(by_signature.items())},
        boxes={k: dict(sorted(v.items())) for k, v in sorted(by_class.items())},
    )


def exposed_test_items(
    split: Sequence[str], groups: Sequence[str], *, train: str = "train"
) -> list[int]:
    """Test items whose constraint group has a member in ``train``."""
    in_train = {g for g, s in zip(groups, split, strict=True) if s == train}
    return [
        i
        for i, (g, s) in enumerate(zip(groups, split, strict=True))
        if s == "test" and g in in_train
    ]


LINKS = ("crop sibling", "similar pair", "same component", "same metadata group", "transitive only")


def probe_link_kinds(
    items: Sequence[Candidate],
    design: PairedDesign,
    components: Mapping[tuple[str, str], str],
    similar: set[frozenset[tuple[str, str]]],
) -> list[str]:
    """For every probe, the strongest direct link to one of its mates ("" for other items).

    ``similar`` holds the image pairs at or above the primary level. A probe whose mates are only
    reached through other members of its group is ``transitive only``.
    """
    members: dict[str, list[int]] = defaultdict(list)
    for index, key in enumerate(design.exposure_group):
        if key is not None:
            members[key].append(index)
    out = [""] * len(items)
    for i, role in enumerate(design.roles):
        if role != "probe":
            continue
        key_i = items[i].item.key
        kinds: set[str] = set()
        for j in members[design.exposure_group[i] or ""]:
            if design.roles[j] != "mate":
                continue
            key_j = items[j].item.key
            if key_j == key_i:
                kinds.add("crop sibling")
            elif frozenset({key_i, key_j}) in similar:
                kinds.add("similar pair")
            elif components.get(key_i) is not None and components.get(key_i) == components.get(
                key_j
            ):
                kinds.add("same component")
            elif (
                items[i].item.group_id is not None
                and items[i].item.group_id == items[j].item.group_id
            ):
                kinds.add("same metadata group")
        out[i] = next((k for k in LINKS if k in kinds), "transitive only")
    return out


def probe_links(kinds: Sequence[str]) -> dict[str, int]:
    counts = Counter(k for k in kinds if k)
    return {k: counts[k] for k in LINKS}
