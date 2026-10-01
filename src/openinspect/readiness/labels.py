"""The M4 label-quality findings that reach the release (M5.5, P1-3).

M4 flagged 437 boxes and images for review over all ingested data; it changed nothing. Training
readiness needs to know which of them are in release v0.1. Every finding gets one category by a
fixed rule (no label is corrected here):

* ``NOT_IN_RELEASE``: the flagged box, or both images of a flagged pair, are not released;
* ``FATAL``: a released box whose geometry is objectively invalid (non-finite or inverted
  coordinates, zero width or height, outside the image): it cannot be exported or trained safely;
* ``TRAINING_RELEVANT``: a released box or image whose flag can change what a model is taught or
  scored on (a box thinner than two pixels, the same box drawn twice, a box drawn twice with two
  labels, a disagreement between the source's annotation formats, a near-duplicate pair of
  released images with different label sets);
* ``LIMITATION_ONLY``: a released box with an atypical size or shape for its class, an ambiguous
  mapping, or a near-duplicate label conflict whose counterpart is not released.
"""

from __future__ import annotations

import csv
import io
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from openinspect.provenance.schema import StrictModel
from openinspect.release.pool import Candidate

Category = Literal["FATAL", "TRAINING_RELEVANT", "LIMITATION_ONLY", "NOT_IN_RELEASE"]
CATEGORIES: tuple[Category, ...] = (
    "FATAL",
    "TRAINING_RELEVANT",
    "LIMITATION_ONLY",
    "NOT_IN_RELEASE",
)
FATAL_SIGNALS = frozenset({"malformed_box", "zero_area_box", "box_out_of_bounds"})
TRAINING_SIGNALS = frozenset(
    {
        "tiny_box",
        "duplicate_box",
        "conflicting_box",
        "source_format_disagreement",
        "near_duplicate_label_conflict",
    }
)
LIMITATION_SIGNALS = frozenset({"extreme_aspect_ratio", "class_size_outlier", "mapping_ambiguity"})
QUEUE = "artifacts/m4/review-required.csv"


class LabelsError(Exception):
    """The M4 review queue cannot be read, or holds a signal without a rule."""


@dataclass(frozen=True)
class Finding:
    review_id: str
    check: str
    signal: str
    source: str
    image: str
    ann_index: int | None
    related_source: str | None
    related_image: str | None
    related_ann_index: int | None


def read_findings(path: Path) -> list[Finding]:
    try:
        rows = list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))))
    except OSError as exc:
        raise LabelsError(f"cannot read {path.name}: {exc}") from exc

    def number(value: str) -> int | None:
        return int(value) if value.strip() else None

    return [
        Finding(
            review_id=r["review_id"],
            check=r["check"],
            signal=r["signal"],
            source=r["source_id"],
            image=r["image_id"],
            ann_index=number(r["ann_index"]),
            related_source=r["related_source_id"] or None,
            related_image=r["related_image_id"] or None,
            related_ann_index=number(r["related_ann_index"]),
        )
        for r in rows
    ]


class Placement(StrictModel):
    review_id: str
    check: str
    signal: str
    source: str
    image: str
    ann_index: int | None
    category: Category
    released_items: list[str]  # global ids holding the flagged box (or image)
    related_items: list[str]  # global ids of the counterpart, for pair findings
    reason: str


def _released(
    items: Sequence[Candidate],
) -> tuple[dict[tuple[str, str], list[int]], dict[tuple[str, str, int], list[int]]]:
    by_image: dict[tuple[str, str], list[int]] = defaultdict(list)
    by_box: dict[tuple[str, str, int], list[int]] = defaultdict(list)
    for k, item in enumerate(items):
        by_image[item.item.key].append(k)
        for b in item.boxes:
            by_box[(item.source, item.item.item_id, b.source_ann_index)].append(k)
    return by_image, by_box


def place(findings: Sequence[Finding], items: Sequence[Candidate]) -> list[Placement]:
    """The category of every finding against the released items (input order kept)."""
    by_image, by_box = _released(items)
    known = FATAL_SIGNALS | TRAINING_SIGNALS | LIMITATION_SIGNALS
    out: list[Placement] = []
    for f in findings:
        if f.signal not in known:
            raise LabelsError(f"{f.review_id}: no category rule for signal {f.signal!r}")
        if f.ann_index is not None:
            held = by_box.get((f.source, f.image, f.ann_index), [])
            where = "the flagged box is" if held else "the flagged box is not"
        else:
            held = by_image.get((f.source, f.image), [])
            where = "the flagged image is" if held else "the flagged image is not"
        related: list[int] = []
        if f.related_image is not None and f.related_source is not None:
            related = (
                by_box.get((f.related_source, f.related_image, f.related_ann_index), [])
                if f.related_ann_index is not None
                else by_image.get((f.related_source, f.related_image), [])
            )
        if f.signal == "near_duplicate_label_conflict":
            if not held and not related:
                category: Category = "NOT_IN_RELEASE"
                reason = "neither image of the pair is released"
            elif held and related:
                category = "TRAINING_RELEVANT"
                reason = "both images of the pair are released with different label sets"
            else:
                category = "LIMITATION_ONLY"
                reason = "only one image of the pair is released"
        elif not held:
            category, reason = "NOT_IN_RELEASE", f"{where} released"
        elif f.signal in FATAL_SIGNALS:
            category, reason = "FATAL", f"{where} released with invalid geometry"
        elif f.signal in TRAINING_SIGNALS:
            category, reason = "TRAINING_RELEVANT", f"{where} released"
        else:
            category, reason = "LIMITATION_ONLY", f"{where} released"
        out.append(
            Placement(
                review_id=f.review_id,
                check=f.check,
                signal=f.signal,
                source=f.source,
                image=f.image,
                ann_index=f.ann_index,
                category=category,
                released_items=sorted(items[k].global_id for k in held),
                related_items=sorted(items[k].global_id for k in related),
                reason=reason,
            )
        )
    return out


class LabelSummary(StrictModel):
    findings: int
    by_category: dict[str, int]
    by_signal: dict[str, dict[str, int]]  # signal -> category -> findings
    by_source: dict[str, dict[str, int]]  # source -> category -> findings
    released_items_affected: dict[str, int]  # category -> distinct released items
    released_boxes_affected: dict[str, int]  # category -> flagged released boxes
    pairs_across_splits: dict[
        str, int
    ]  # regime -> released conflict pairs whose items differ in split
    fatal_items: list[str]


def summarize(
    placements: Sequence[Placement], schemes: Mapping[str, Mapping[str, str]]
) -> LabelSummary:
    """``schemes`` maps a regime name to {global id: split}."""
    by_category = Counter(p.category for p in placements)
    by_signal: dict[str, Counter[str]] = defaultdict(Counter)
    by_source: dict[str, Counter[str]] = defaultdict(Counter)
    items: dict[str, set[str]] = defaultdict(set)
    boxes: Counter[str] = Counter()
    for p in placements:
        by_signal[p.signal][p.category] += 1
        by_source[p.source][p.category] += 1
        items[p.category].update(p.released_items)
        if p.ann_index is not None and p.released_items:
            boxes[p.category] += 1
    crossing: dict[str, int] = {}
    conflicts = [p for p in placements if p.category == "TRAINING_RELEVANT" and p.related_items]
    for name, split in schemes.items():
        crossing[name] = sum(
            1
            for p in conflicts
            if {split[g] for g in p.released_items} != {split[g] for g in p.related_items}
            or len({split[g] for g in [*p.released_items, *p.related_items]}) > 1
        )
    return LabelSummary(
        findings=len(placements),
        by_category={c: by_category[c] for c in CATEGORIES},
        by_signal={s: {c: v[c] for c in CATEGORIES if v[c]} for s, v in sorted(by_signal.items())},
        by_source={s: {c: v[c] for c in CATEGORIES if v[c]} for s, v in sorted(by_source.items())},
        released_items_affected={c: len(items[c]) for c in CATEGORIES},
        released_boxes_affected={c: boxes[c] for c in CATEGORIES},
        pairs_across_splits=crossing,
        fatal_items=sorted(items["FATAL"]),
    )
