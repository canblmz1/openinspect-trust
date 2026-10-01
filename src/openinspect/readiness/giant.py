"""Why does one PCB-Defect constraint group hold most of its crops? (M5.5)

The A1 constraint group of a crop is the union of four kinds of constraint: its parent scan
(``crop_parent``), the parent's design family (``metadata_group``), the parent's M3 visual
similarity component (``similarity_component``, computed on whole scans resized to 224x224 and
inherited by every crop) and identical files. The diagnostics below separate them:

* a decomposition: the largest group when only some kinds of constraint are joined;
* the scan-level similarity graph at the source's primary threshold: size, number of design
  families spanned, edge and all-pair minimum similarity, the chaining gap and the diameter of
  its largest component; the same for DINOv2-base;
* a threshold sweep of the largest scan component under both models;
* the crop-level graph: what the components would be if they were computed on the crops
  themselves instead of being inherited from the scans.

The verdict follows rules fixed in :func:`verdict` before the diagnostics ran on the release.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence

import numpy as np
from numpy.typing import NDArray
from pydantic import Field

from openinspect.dedup.graph import collect_edges, components, multi_member_groups
from openinspect.provenance.schema import StrictModel
from openinspect.release.groups import KINDS, Constraint, union_groups
from openinspect.release.pool import Candidate

COHESIVE_MARGIN = 0.0  # all pairs at or above the threshold: every pair is itself similar
CHAINING_GAP = 0.05  # edge minimum minus all-pair minimum
CHAINING_DIAMETER = 3
REPRESENTATION_SHARE = 0.25  # the other model's largest scan component as a share of the scans
INHERITANCE_SHARE = 0.5  # crop-level largest group as a share of the inherited giant


class Decomposition(StrictModel):
    kinds: list[str]
    groups: int  # groups with at least two items
    largest: int
    singletons: int


class ScanGraph(StrictModel):
    model: str
    threshold: float
    scans: int
    edges: int
    components: int
    largest: int
    largest_families: int  # design families (group_id) in the largest component
    families: int
    edge_min: float | None
    all_pairs_min: float | None
    all_pairs_mean: float | None
    chaining_gap: float | None
    diameter: int | None  # longest shortest path, in edges, inside the largest component
    mean_path: float | None


class SweepPoint(StrictModel):
    model: str
    threshold: float
    largest_share: float
    components: int


class CropGraph(StrictModel):
    model: str
    threshold: float
    crops: int
    largest_component: int  # crop-level similarity alone
    largest_group_with_constraints: int  # + crop parents + design families + identical files
    cross_scan_edges: int
    cross_family_edges: int


class GiantComponent(StrictModel):
    source: str
    items: int
    largest_group: int
    decomposition: list[Decomposition]
    scan_graphs: list[ScanGraph]
    sweep: list[SweepPoint]
    crop_graphs: list[CropGraph]
    verdict: str = Field(description="A, B, C, D or E, with the causes found")
    causes: list[str]
    rules: list[str]


def decompose(
    items: Sequence[Candidate], found: Sequence[Constraint], source: str
) -> list[Decomposition]:
    """The largest group of ``source``'s items when only some constraint kinds are joined."""
    idx = [i for i, item in enumerate(items) if item.source == source]
    local = {i: k for k, i in enumerate(idx)}
    subsets = [
        ("crop_parent",),
        ("crop_parent", "metadata_group"),
        ("crop_parent", "similarity_component"),
        ("similarity_component",),
        ("metadata_group",),
        tuple(KINDS),
    ]
    out: list[Decomposition] = []
    for kinds in subsets:
        chosen = [
            Constraint(c.kind, c.key, tuple(local[m] for m in c.members if m in local))
            for c in found
            if c.kind in kinds
        ]
        roots = union_groups(len(idx), [c for c in chosen if len(c.members) > 1])
        sizes = np.bincount(np.array(roots, dtype=np.int64), minlength=len(idx))
        multi = sizes[sizes > 1]
        out.append(
            Decomposition(
                kinds=list(kinds),
                groups=len(multi),
                largest=int(multi.max()) if len(multi) else 1,
                singletons=int((sizes == 1).sum()),
            )
        )
    return out


def _diameter(
    n: int, edges: Sequence[tuple[int, int]], members: Sequence[int]
) -> tuple[int, float]:
    adjacency: dict[int, list[int]] = {m: [] for m in members}
    for a, b in edges:
        if a in adjacency and b in adjacency:
            adjacency[a].append(b)
            adjacency[b].append(a)
    longest, total, count = 0, 0, 0
    for start in members:
        seen = {start: 0}
        queue = deque([start])
        while queue:
            node = queue.popleft()
            for nxt in adjacency[node]:
                if nxt not in seen:
                    seen[nxt] = seen[node] + 1
                    queue.append(nxt)
        longest = max(longest, max(seen.values()))
        total += sum(seen.values())
        count += len(seen) - 1
    return longest, (total / count if count else 0.0)


def scan_graph(
    vectors: NDArray[np.float32], families: Sequence[str | None], threshold: float, model: str
) -> ScanGraph:
    """The similarity graph of one source's whole images at ``threshold``."""
    i, j, sims = collect_edges(vectors, threshold)
    labels = components(len(vectors), [(i, j)])
    groups = multi_member_groups(labels)
    if not groups:
        return ScanGraph(
            model=model,
            threshold=threshold,
            scans=len(vectors),
            edges=len(i),
            components=0,
            largest=1,
            largest_families=1,
            families=len({f for f in families if f is not None}),
            edge_min=None,
            all_pairs_min=None,
            all_pairs_mean=None,
            chaining_gap=None,
            diameter=None,
            mean_path=None,
        )
    big = max(groups, key=lambda g: (len(g.members), -g.label))
    members = big.members.tolist()
    sub = vectors[big.members].astype(np.float64)
    block = sub @ sub.T
    upper = block[np.triu_indices(len(members), k=1)]
    inside = np.isin(i, big.members) & np.isin(j, big.members)
    edge_min = float(sims[inside].min())
    pairs = [(int(a), int(b)) for a, b in zip(i[inside].tolist(), j[inside].tolist(), strict=True)]
    diameter, mean_path = _diameter(len(vectors), pairs, members)
    return ScanGraph(
        model=model,
        threshold=threshold,
        scans=len(vectors),
        edges=len(i),
        components=len(groups),
        largest=len(members),
        largest_families=len({families[m] for m in members if families[m] is not None}),
        families=len({f for f in families if f is not None}),
        edge_min=round(edge_min, 6),
        all_pairs_min=round(float(upper.min()), 6),
        all_pairs_mean=round(float(upper.mean()), 6),
        chaining_gap=round(edge_min - float(upper.min()), 6),
        diameter=diameter,
        mean_path=round(mean_path, 4),
    )


def sweep(
    vectors: NDArray[np.float32], thresholds: Sequence[float], model: str
) -> list[SweepPoint]:
    out: list[SweepPoint] = []
    for t in thresholds:
        i, j, _ = collect_edges(vectors, t)
        groups = multi_member_groups(components(len(vectors), [(i, j)]))
        largest = max((len(g.members) for g in groups), default=1)
        out.append(
            SweepPoint(
                model=model,
                threshold=round(t, 6),
                largest_share=round(largest / max(len(vectors), 1), 6),
                components=len(groups),
            )
        )
    return out


def crop_graph(
    items: Sequence[Candidate],
    vectors: NDArray[np.float32],
    threshold: float,
    model: str,
    sha256: Sequence[str],
) -> CropGraph:
    """Components computed on the crops themselves, alone and joined with the other constraints."""
    i, j, _ = collect_edges(vectors, threshold)
    labels = components(len(items), [(i, j)])
    groups = multi_member_groups(labels)
    parents = [it.item.key for it in items]
    families = [it.item.group_id for it in items]
    constraints_found: list[Constraint] = []
    for k, key in enumerate(sorted(set(parents))):
        members = tuple(m for m, p in enumerate(parents) if p == key)
        if len(members) > 1:
            constraints_found.append(Constraint("crop_parent", f"p{k}", members))
    for k, fam in enumerate(sorted({f for f in families if f is not None})):
        members = tuple(m for m, f in enumerate(families) if f == fam)
        if len(members) > 1:
            constraints_found.append(Constraint("metadata_group", f"f{k}", members))
    for g in groups:
        constraints_found.append(
            Constraint("similarity_component", str(g.label), tuple(g.members.tolist()))
        )
    by_sha: dict[str, list[int]] = {}
    for k, digest in enumerate(sha256):
        by_sha.setdefault(digest, []).append(k)
    for digest, members_list in by_sha.items():
        if len(members_list) > 1:
            constraints_found.append(Constraint("exact_duplicate", digest, tuple(members_list)))
    roots = union_groups(len(items), constraints_found)
    sizes = np.bincount(np.array(roots, dtype=np.int64), minlength=len(items))
    cross_scan = sum(
        1 for a, b in zip(i.tolist(), j.tolist(), strict=True) if parents[a] != parents[b]
    )
    cross_family = sum(
        1 for a, b in zip(i.tolist(), j.tolist(), strict=True) if families[a] != families[b]
    )
    return CropGraph(
        model=model,
        threshold=threshold,
        crops=len(items),
        largest_component=max((len(g.members) for g in groups), default=1),
        largest_group_with_constraints=int(sizes.max()) if len(sizes) else 0,
        cross_scan_edges=cross_scan,
        cross_family_edges=cross_family,
    )


RULES = [
    "A (visually cohesive): every pair of scans in the largest primary-level component is itself "
    "at or above the threshold (all-pair minimum >= threshold).",
    f"B (transitive chaining): the chaining gap (edge minimum minus all-pair minimum) is at least "
    f"{CHAINING_GAP} and the diameter is at least {CHAINING_DIAMETER} edges.",
    f"C (crop-generation style): with components computed on the crops instead of inherited from "
    f"the scans, the largest group (with crop parents, design families and identical files) is "
    f"below {INHERITANCE_SHARE:.0%} of the inherited group.",
    f"D (representation artifact): the other model's largest scan component at its own primary "
    f"threshold holds less than {REPRESENTATION_SHARE:.0%} of the scans, while the primary's "
    "holds more.",
    "E (mixture): two or more of B, C and D hold.",
]


def verdict(
    primary: ScanGraph, other: ScanGraph, crops: CropGraph | None, inherited_largest: int
) -> tuple[str, list[str]]:
    causes: list[str] = []
    if (
        primary.all_pairs_min is not None
        and primary.all_pairs_min >= primary.threshold - COHESIVE_MARGIN
    ):
        return "A", ["every pair of the largest component is itself similar"]
    if (
        primary.chaining_gap is not None
        and primary.diameter is not None
        and primary.chaining_gap >= CHAINING_GAP
        and primary.diameter >= CHAINING_DIAMETER
    ):
        causes.append(
            f"B: chaining gap {primary.chaining_gap:.3f}, diameter {primary.diameter} edges"
        )
    if (
        crops is not None
        and crops.largest_group_with_constraints < INHERITANCE_SHARE * inherited_largest
    ):
        causes.append(
            f"C: crop-level components give a largest group of {crops.largest_group_with_constraints} "
            f"instead of the inherited {inherited_largest}"
        )
    primary_share = primary.largest / max(primary.scans, 1)
    other_share = other.largest / max(other.scans, 1)
    if other_share < REPRESENTATION_SHARE <= primary_share:
        causes.append(
            f"D: {other.model} holds {other.largest} of {other.scans} scans in its largest component, "
            f"{primary.model} {primary.largest}"
        )
    if len(causes) >= 2:
        return "E", causes
    if len(causes) == 1:
        return causes[0][0], causes
    return "undetermined", causes


def families_of(
    keys: Sequence[tuple[str, str]], groups: Mapping[tuple[str, str], str | None]
) -> list[str | None]:
    return [groups.get(k) for k in keys]
