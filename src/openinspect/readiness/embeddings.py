"""The data-dependent half of M5.5: components of each model, base pairs, crop embeddings.

These functions read the M3 embedding caches in the data directory (no model is loaded for whole
images: every vector is cached). Only the crops of a source with a crop policy may need the model
once, because M3 embedded the original images, not the release crops. Results are written as small
artifacts so that the rest of M5.5 runs from committed files alone.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from openinspect.dedup.analysis import GlobalGraph, global_graph, make_views
from openinspect.dedup.cache import EmbeddingCache
from openinspect.dedup.compute import FeatureSet, HashStore, compute_features
from openinspect.dedup.embedder import Embedder, EmbedderSpec
from openinspect.dedup.graph import collect_edges, components, multi_member_groups
from openinspect.dedup.hashing import PHASH_VERSION
from openinspect.dedup.inventory import ImageItem
from openinspect.dedup.thresholds import Thresholds

MAX_EDGES = 30_000_000
CHAINING_SHARE = 0.25  # docs/M3_PROTOCOL.md section 8, as in the M3 audit


def model_cache(data: Path, spec: EmbedderSpec) -> EmbeddingCache:
    return EmbeddingCache(
        data,
        model_key=spec.model_key,
        preprocessing_version=spec.preprocessing_version,
        backend=spec.backend,
        dim=spec.dim,
    )


def m3_hashes(data: Path) -> HashStore:
    return HashStore(data / "m3" / "hashes" / f"{PHASH_VERSION}.jsonl")


@dataclass(frozen=True)
class ModelGroups:
    spec: EmbedderSpec
    thresholds: Thresholds
    features: FeatureSet
    primary: dict[str, str]  # source -> near | family (the M3 chaining rule)
    largest_share: dict[str, float]  # source -> largest family-level component / images
    components: dict[tuple[str, str], str]  # (source, image) -> group id at the primary level
    graph: GlobalGraph


def chaining(features: FeatureSet, family: float) -> tuple[dict[str, str], dict[str, float]]:
    """The M3 chaining rule per source: ``near`` if its largest family-level component (within the
    source) holds more than a quarter of its images."""
    primary: dict[str, str] = {}
    shares: dict[str, float] = {}
    for view in make_views(features):
        i, j, _ = collect_edges(view.vectors, family, max_edges=MAX_EDGES)
        groups = multi_member_groups(components(len(view.items), [(i, j)]))
        largest = max((len(g.members) for g in groups), default=1)
        shares[view.source] = round(largest / max(len(view.items), 1), 6)
        primary[view.source] = "near" if largest > CHAINING_SHARE * len(view.items) else "family"
    return primary, shares


def model_groups(
    items: Sequence[ImageItem], data: Path, spec: EmbedderSpec, thresholds: Thresholds
) -> ModelGroups:
    """Components of one model over all ingested images, from its cache (no model needed)."""
    features = compute_features(
        items, spec=spec, cache=model_cache(data, spec), hashes=m3_hashes(data), make_embedder=None
    )
    primary, shares = chaining(features, thresholds.family)
    graph = global_graph(features, thresholds, MAX_EDGES)
    found: dict[tuple[str, str], str] = {}
    for row in graph.rows:
        for member in row.members:
            source, _, image = member.partition(":")
            if primary.get(source) == row.level:
                found[(source, image)] = row.group_id
    return ModelGroups(spec, thresholds, features, primary, shares, found, graph)


def similar_pairs(
    groups: ModelGroups, keep: set[tuple[str, str]]
) -> list[tuple[str, str, str, str, float]]:
    """Pairs at or above each pair's primary level, between images in ``keep`` (sorted)."""
    i, j, sims = groups.graph.edges
    items = groups.features.items
    t = groups.thresholds
    out: list[tuple[str, str, str, str, float]] = []
    for a, b, s in zip(i.tolist(), j.tolist(), sims.tolist(), strict=True):
        ka, kb = items[a].key, items[b].key
        if ka not in keep or kb not in keep:
            continue
        both_family = groups.primary.get(ka[0]) == groups.primary.get(kb[0]) == "family"
        if s >= t.near or (s >= t.family and both_family):
            first, second = sorted((ka, kb))
            out.append((first[0], first[1], second[0], second[1], round(float(s), 6)))
    return sorted(out)


def vectors_by_key(features: FeatureSet) -> dict[tuple[str, str], NDArray[np.float32]]:
    return {item.key: features.vectors[k] for k, item in enumerate(features.items)}


def crop_features(
    crops: Sequence[ImageItem],
    data: Path,
    spec: EmbedderSpec,
    make_embedder: Callable[[], Embedder] | None,
    *,
    hashes_path: Path,
) -> FeatureSet:
    """Embeddings of released crops (cached by the crop's SHA-256 like any other image)."""
    return compute_features(
        crops,
        spec=spec,
        cache=model_cache(data, spec),
        hashes=HashStore(hashes_path),
        make_embedder=make_embedder,
    )


def thresholds_of(
    audit: Mapping[str, object], *, robustness: bool
) -> Thresholds:  # pragma: no cover - thin wrapper, exercised by the CLI
    raw = audit["robustness"]["other_thresholds"] if robustness else audit["thresholds"]  # type: ignore[index]
    return Thresholds.model_validate(raw)
