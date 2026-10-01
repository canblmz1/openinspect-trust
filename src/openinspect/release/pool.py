"""The release pool: candidate items, exclusions with reasons, quotas and a stratified sample.

Every image either becomes a candidate (as it is, or as crops for a source with a crop policy) or
is excluded with a reason; nothing is dropped silently. Quotas keep every source at or below the
configured share of the release; a source above its quota is sampled with a fixed seed,
stratified by the set of normalized classes in each image, so the sample keeps the source's
class mix.
"""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath

from openinspect.dedup.inventory import ImageItem
from openinspect.release.config import ReleaseConfig, SizeRange
from openinspect.release.crops import Rect, plan_crops, shift
from openinspect.release.ids import check_unique, global_id
from openinspect.taxonomy.config import Taxonomy
from openinspect.taxonomy.mapping import MappedBox, MappedImage

BBox = tuple[float, float, float, float]


class ReleaseError(Exception):
    """The release cannot be assembled as configured."""


@dataclass(frozen=True)
class ReleaseBox:
    source_ann_index: int
    original_label: str
    normalized_label: str
    mapping_status: str
    class_id: int
    bbox: BBox  # in pixels of the released image
    bbox_source: BBox  # in pixels of the original image


@dataclass(frozen=True)
class Candidate:
    global_id: str
    item: ImageItem  # the original image (the parent of a crop)
    crop: Rect | None
    width: int
    height: int
    boxes: tuple[ReleaseBox, ...]

    @property
    def source(self) -> str:
        return self.item.source

    @property
    def signature(self) -> str:
        """The sorted normalized classes of the item: its stratum."""
        return ";".join(sorted({b.normalized_label for b in self.boxes}))

    @property
    def extension(self) -> str:
        return ".png" if self.crop is not None else PurePosixPath(self.item.item_id).suffix.lower()

    @property
    def file_name(self) -> str:
        return f"{self.global_id}{self.extension}"


@dataclass(frozen=True)
class Exclusion:
    source: str
    source_item_id: str
    reason: str
    detail: str = ""


def _release_box(m: MappedBox, class_ids: Mapping[str, int], rect: Rect | None) -> ReleaseBox:
    label = m.normalized_label or ""
    return ReleaseBox(
        source_ann_index=m.box.ann_index,
        original_label=m.box.original_label,
        normalized_label=label,
        mapping_status=m.status,
        class_id=class_ids[label],
        bbox=m.box.bbox if rect is None else shift(m.box.bbox, rect),
        bbox_source=m.box.bbox,
    )


def _valid(m: MappedBox) -> bool:
    return m.box.finite and m.box.width > 0 and m.box.height > 0 and m.box.in_bounds


def build_candidates(
    images: Sequence[MappedImage], taxonomy: Taxonomy, config: ReleaseConfig
) -> tuple[list[Candidate], list[Exclusion]]:
    """Candidates and exclusions for every image, in (source, image) order."""
    class_ids = {name: k for k, name in enumerate(taxonomy.benchmark_classes)}
    candidates: list[Candidate] = []
    excluded: list[Exclusion] = []
    for image in sorted(images, key=lambda i: i.item.key):
        item = image.item
        policy = config.crops.get(item.source)
        if not image.boxes and (config.negatives == "exclude" or policy is not None):
            excluded.append(Exclusion(item.source, item.item_id, "no_boxes"))
            continue
        if policy is not None:
            if not item.width or not item.height:
                excluded.append(Exclusion(item.source, item.item_id, "unknown_size"))
                continue
            outcome = plan_crops(item.width, item.height, image.boxes, policy)
            by_index = {m.box.ann_index: m for m in image.boxes}
            for plan in outcome.plans:
                side = plan.rect[2] - plan.rect[0]
                candidates.append(
                    Candidate(
                        global_id=global_id(item.source, item.sha256, plan.rect),
                        item=item,
                        crop=plan.rect,
                        width=side,
                        height=plan.rect[3] - plan.rect[1],
                        boxes=tuple(
                            _release_box(by_index[k], class_ids, plan.rect) for k in plan.boxes
                        ),
                    )
                )
            excluded.append(
                Exclusion(
                    item.source,
                    item.item_id,
                    "replaced_by_crops" if outcome.plans else "no_crop",
                    f"{len(outcome.plans)} crops, {len(outcome.covered)} anchors covered by them",
                )
            )
            excluded.extend(
                Exclusion(item.source, item.item_id, f"crop_{reason}", f"anchor box {anchor}")
                for anchor, reason in outcome.rejected
            )
            continue
        if image.eligibility == "excluded":
            excluded.append(
                Exclusion(
                    item.source, item.item_id, "non_benchmark_class", ";".join(image.excluded_by)
                )
            )
            continue
        if not all(_valid(m) for m in image.boxes):
            excluded.append(Exclusion(item.source, item.item_id, "invalid_box"))
            continue
        if not item.width or not item.height:
            excluded.append(Exclusion(item.source, item.item_id, "unknown_size"))
            continue
        candidates.append(
            Candidate(
                global_id=global_id(item.source, item.sha256),
                item=item,
                crop=None,
                width=item.width,
                height=item.height,
                boxes=tuple(_release_box(m, class_ids, None) for m in image.boxes),
            )
        )
    check_unique(c.global_id for c in candidates)
    return candidates, excluded


def largest_remainder(weights: Mapping[str, float], total: int) -> dict[str, int]:
    """Integers proportional to ``weights`` that sum to ``total`` (ties in the order given)."""
    whole = sum(weights.values())
    if whole <= 0:
        return dict.fromkeys(weights, 0)
    exact = {k: total * w / whole for k, w in weights.items()}
    counts = {k: math.floor(v) for k, v in exact.items()}
    left = total - sum(counts.values())
    order = list(weights)
    for key in sorted(exact, key=lambda k: (-(exact[k] - counts[k]), order.index(k)))[:left]:
        counts[key] += 1
    return counts


def quotas(available: Mapping[str, int], share: float, size: SizeRange) -> dict[str, int]:
    """The most images per source such that no source exceeds ``share`` of the release.

    A source above its share is cut to the largest count the others allow; then the release is
    scaled down proportionally if it exceeds ``size.max``. Fewer than ``size.min`` is an error.
    """
    counts = dict(available)
    for _ in range(4 * len(counts) + 4):
        total = sum(counts.values())
        over = [s for s in sorted(counts) if counts[s] > share * total]
        if over:
            source = max(over, key=lambda s: (counts[s], s))
            others = total - counts[source]
            counts[source] = math.floor(share * others / (1 - share))
            continue
        if total > size.max:
            counts = largest_remainder({s: float(n) for s, n in counts.items()}, size.max)
            continue
        break
    else:  # pragma: no cover - the counts only decrease, so the loop settles quickly
        raise ReleaseError("the quotas did not settle")
    total = sum(counts.values())
    if total < size.min:
        raise ReleaseError(
            f"only {total} images fit the share limit of {share:.0%}; the release needs {size.min}"
        )
    return counts


def _order_key(seed: int, value: str) -> str:
    return hashlib.sha256(f"{seed}:{value}".encode()).hexdigest()


def sample(
    candidates: Sequence[Candidate], counts: Mapping[str, int], seed: int
) -> tuple[list[Candidate], list[Exclusion]]:
    """A seeded sample per source, stratified by the item's classes (largest remainder)."""
    by_source: dict[str, list[Candidate]] = defaultdict(list)
    for c in candidates:
        by_source[c.source].append(c)
    chosen: list[Candidate] = []
    dropped: list[Exclusion] = []
    for source, members in sorted(by_source.items()):
        want = counts.get(source, 0)
        if want >= len(members):
            chosen.extend(members)
            continue
        strata: dict[str, list[Candidate]] = defaultdict(list)
        for c in members:
            strata[c.signature].append(c)
        take = largest_remainder({k: float(len(v)) for k, v in strata.items()}, want)
        for signature, group in sorted(strata.items()):
            ordered = sorted(group, key=lambda c: _order_key(seed, c.global_id))
            chosen.extend(ordered[: take[signature]])
            dropped.extend(
                Exclusion(c.source, c.item.item_id, "not_sampled", c.global_id)
                for c in ordered[take[signature] :]
            )
    chosen.sort(key=lambda c: (c.source, c.global_id))
    dropped.sort(key=lambda e: (e.source, e.source_item_id, e.detail))
    return chosen, dropped
