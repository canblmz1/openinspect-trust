"""What a split achieves, measured after it is made, and the leakage invariants (SPEC 7.6).

Nothing about a split is assumed: crossing constraints, crossing similar pairs from M3, shared
file hashes and the shares per split are counted on the final assignment. The pairs come from
the M3 similarity audit (machine-detected, not human-validated).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pyarrow.parquet as pq

from openinspect.provenance.schema import StrictModel
from openinspect.release.groups import Constraint, crossing
from openinspect.release.pool import Candidate
from openinspect.release.splits import EXCLUDED

NEAR = "NEAR_DUPLICATE"
FAMILY = "SAME_FAMILY_OR_SCENE"


@dataclass(frozen=True)
class ImagePair:
    source_a: str
    image_a: str
    source_b: str
    image_b: str
    category: str


def read_image_pairs(path: Path) -> list[ImagePair]:
    """The candidate pairs of ``artifacts/m3/duplicate-pairs.parquet``."""
    columns = ("source_a", "image_a", "source_b", "image_b", "category")
    data = pq.read_table(path, columns=list(columns)).to_pydict()
    return [
        ImagePair(str(a), str(ia), str(b), str(ib), str(c))
        for a, ia, b, ib, c in zip(*(data[k] for k in columns), strict=True)
    ]


def primary_pair(pair: ImagePair, primary: Mapping[str, str]) -> bool:
    """Is the pair at or above the primary level of both its sources (the level A1 groups by)?"""
    if pair.category == NEAR:
        return True
    return (
        pair.category == FAMILY
        and primary.get(pair.source_a) == primary.get(pair.source_b) == "family"
    )


class SplitMeasure(StrictModel):
    images: dict[str, dict[str, int]]  # split -> source -> items ("excluded" included)
    boxes: dict[str, dict[str, int]]  # split -> normalized class -> boxes
    shares: dict[str, float]  # split -> share of the assigned items
    constraints_crossing: dict[str, int]  # constraint kind -> constraints in more than one split
    pairs_crossing: dict[str, int]  # M3 category -> image pairs whose items lie in two splits
    pairs_train_test: dict[str, int]  # M3 category -> such pairs between train and test
    primary_pairs_crossing: int  # crossing pairs at or above both sources' primary level
    sha256_crossing: int  # file hashes that occur in more than one split (I2)

    @property
    def supplied_groups_crossing(self) -> int:
        return sum(self.constraints_crossing.values())


def measure(
    items: Sequence[Candidate],
    split_of: Sequence[str],
    found: Sequence[Constraint],
    pairs: Sequence[ImagePair],
    primary: Mapping[str, str],
    sha256: Sequence[str],
) -> SplitMeasure:
    assigned: list[str | None] = [None if s == EXCLUDED else s for s in split_of]
    images: dict[str, Counter[str]] = defaultdict(Counter)
    boxes: dict[str, Counter[str]] = defaultdict(Counter)
    for item, split in zip(items, split_of, strict=True):
        images[split][item.source] += 1
        boxes[split].update(b.normalized_label for b in item.boxes)
    n_assigned = sum(1 for s in assigned if s is not None)
    shares = Counter(s for s in assigned if s is not None)
    by_image: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, item in enumerate(items):
        by_image[item.item.key].append(index)
    crossing_pairs: Counter[str] = Counter()
    train_test: Counter[str] = Counter()
    primary_crossing = 0
    for pair in pairs:
        a = {assigned[i] for i in by_image.get((pair.source_a, pair.image_a), [])} - {None}
        b = {assigned[i] for i in by_image.get((pair.source_b, pair.image_b), [])} - {None}
        if not a or not b or (len(a) == 1 and a == b):
            continue
        crossing_pairs[pair.category] += 1
        if ("train" in a and "test" in b) or ("test" in a and "train" in b):
            train_test[pair.category] += 1
        primary_crossing += int(primary_pair(pair, primary))
    files: dict[str, set[str]] = defaultdict(set)
    for digest, target in zip(sha256, assigned, strict=True):
        if target is not None:
            files[digest].add(target)
    return SplitMeasure(
        images={s: dict(sorted(c.items())) for s, c in sorted(images.items())},
        boxes={s: dict(sorted(c.items())) for s, c in sorted(boxes.items())},
        shares={s: n / n_assigned for s, n in sorted(shares.items())} if n_assigned else {},
        constraints_crossing=crossing(found, assigned),
        pairs_crossing=dict(sorted(crossing_pairs.items())),
        pairs_train_test=dict(sorted(train_test.items())),
        primary_pairs_crossing=primary_crossing,
        sha256_crossing=sum(1 for splits in files.values() if len(splits) > 1),
    )


# ------------------------------------------------------------------------------ invariants


class Invariant(StrictModel):
    id: str
    rule: str
    status: Literal["PASS", "FAIL"]
    detail: str


@dataclass(frozen=True)
class Provenance:
    """The provenance fields I7 and I8 check for one released item."""

    source: str
    source_item_id: str
    source_url: str
    licence: str
    sha256_source: str


RULES = {
    "I1": "for every B fold, test holds only the held-out source and no train or val item comes from it",
    "I2": "no file SHA-256 occurs in two splits of any scheme",
    "I3": "every item is in exactly one split of every scheme; global ids are unique",
    "I4": "in A1 and B no metadata group (group_id) crosses a split (A0: measured)",
    "I5": "in A1 and B no visual similarity component and no M3 pair at the primary level crosses a split (A0: measured)",
    "I6": "the same items and seed give the same split, whatever the order of the items",
    "I7": "every item has its source, original file id, source URL, licence and original SHA-256",
    "I8": "every licence is on the allowlist",
    "I9": "every released box has an EXACT or COMPATIBLE mapping onto a benchmark class",
}


def _status(ok: bool) -> Literal["PASS", "FAIL"]:
    return "PASS" if ok else "FAIL"


def invariants(
    items: Sequence[Candidate],
    schemes: Mapping[str, Sequence[str]],
    measures: Mapping[str, SplitMeasure],
    provenance: Sequence[Provenance],
    *,
    allowlist: set[str],
    benchmark: set[str],
    rebuild: Callable[[], Mapping[str, Sequence[str]]],
) -> list[Invariant]:
    """I1 to I9 on the final assignment.

    ``rebuild`` re-derives every scheme from the items in another order and returns the splits
    aligned to ``items``; I6 holds when they are identical.
    """
    results: list[Invariant] = []
    folds = {name: split for name, split in schemes.items() if name.startswith("B-")}
    wrong: dict[str, list[str]] = {}
    for name, split in folds.items():
        training = {items[i].source for i, s in enumerate(split) if s in ("train", "val")}
        testing = {items[i].source for i, s in enumerate(split) if s == "test"}
        held_out = name.removeprefix("B-")
        problems = sorted(training & testing) + sorted(testing - {held_out})
        if problems:
            wrong[name] = problems
    results.append(
        Invariant(
            id="I1",
            rule=RULES["I1"],
            status=_status(bool(folds) and not wrong),
            detail=f"{len(folds)} folds; sources out of place: "
            + (", ".join(f"{k}: {v}" for k, v in wrong.items()) or "none"),
        )
    )
    shared = {name: m.sha256_crossing for name, m in measures.items()}
    results.append(
        Invariant(
            id="I2",
            rule=RULES["I2"],
            status=_status(not any(shared.values())),
            detail=", ".join(f"{k} {v}" for k, v in shared.items()),
        )
    )
    allowed = {"train", "val", "test", EXCLUDED}
    complete = all(len(split) == len(items) and set(split) <= allowed for split in schemes.values())
    unique = len({item.global_id for item in items}) == len(items)
    results.append(
        Invariant(
            id="I3",
            rule=RULES["I3"],
            status=_status(complete and unique),
            detail=f"{len(items):,} items, {len(schemes)} schemes",
        )
    )
    guarded = [name for name in measures if name != "A0"]
    groups = {name: measures[name].constraints_crossing["metadata_group"] for name in measures}
    results.append(
        Invariant(
            id="I4",
            rule=RULES["I4"],
            status=_status(all(groups[n] == 0 for n in guarded)),
            detail=", ".join(f"{k} {v}" for k, v in groups.items()),
        )
    )
    similar = {
        name: (m.constraints_crossing["similarity_component"], m.primary_pairs_crossing)
        for name, m in measures.items()
    }
    results.append(
        Invariant(
            id="I5",
            rule=RULES["I5"],
            status=_status(all(similar[n] == (0, 0) for n in guarded)),
            detail=", ".join(f"{k} {c} components / {p} pairs" for k, (c, p) in similar.items()),
        )
    )
    again = rebuild()
    same = set(again) == set(schemes) and all(
        list(schemes[name]) == list(again[name]) for name in schemes
    )
    results.append(
        Invariant(
            id="I6",
            rule=RULES["I6"],
            status=_status(same),
            detail="re-derived from the items in reverse order",
        )
    )
    missing = [
        p.source + ":" + p.source_item_id
        for p in provenance
        if not all((p.source, p.source_item_id, p.source_url, p.licence, p.sha256_source))
    ]
    results.append(
        Invariant(
            id="I7",
            rule=RULES["I7"],
            status=_status(not missing and len(provenance) == len(items)),
            detail=f"{len(missing)} items with a missing field",
        )
    )
    licences = sorted({p.licence for p in provenance})
    results.append(
        Invariant(
            id="I8",
            rule=RULES["I8"],
            status=_status(set(licences) <= allowlist),
            detail="licences: " + ", ".join(licences),
        )
    )
    bad = [
        item.global_id
        for item in items
        for b in item.boxes
        if b.normalized_label not in benchmark or b.mapping_status not in ("EXACT", "COMPATIBLE")
    ]
    results.append(
        Invariant(
            id="I9",
            rule=RULES["I9"],
            status=_status(not bad),
            detail=f"{sum(len(i.boxes) for i in items):,} boxes, {len(bad)} outside the benchmark classes",
        )
    )
    return results
