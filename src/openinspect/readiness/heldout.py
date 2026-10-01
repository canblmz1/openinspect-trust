"""Two source-held-out regimes that answer two questions (M5.5).

* **B-strict** (the M5 split ``B-<source>``): the held-out source is the test set, and training
  items that share a constraint with a held-out item (a machine-detected visual similarity
  component across sources) are excluded. *How does a model generalize when both source identity
  and the known machine-similarity overlap are removed?*
* **B-natural** (new): the held-out source is the test set, every other item is available for
  train and validation, split group-aware the same way; naturally similar cross-source examples are
  *not* removed because a similarity graph links them. *How does a model generalize to an unseen
  acquisition source under naturally occurring cross-source similarity?*

Both keep source integrity: every item of the held-out source is in test, and no other item is.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from openinspect.release.pool import Candidate
from openinspect.release.splits import EXCLUDED, group_split


def natural_held_out_split(
    items: Sequence[Candidate], groups: Sequence[str], source: str, val_share: float, seed: int
) -> list[str]:
    """B-natural: ``test`` for ``source``; train and val, group-aware, for every other item."""
    eligible = [item.source != source for item in items]
    inner = group_split(
        items, groups, {"train": 1 - val_share, "val": val_share}, seed, eligible=eligible
    )
    return [
        "test" if item.source == source else (inner[i] or EXCLUDED) for i, item in enumerate(items)
    ]


@dataclass(frozen=True)
class Purity:
    held_out: str
    test_sources: list[str]
    held_out_items_outside_test: int
    other_items_in_test: int
    excluded: int

    @property
    def ok(self) -> bool:
        return (
            self.test_sources == [self.held_out]
            and self.held_out_items_outside_test == 0
            and self.other_items_in_test == 0
        )


def purity(items: Sequence[Candidate], split: Sequence[str], held_out: str) -> Purity:
    """Source integrity of a held-out split, measured."""
    return Purity(
        held_out=held_out,
        test_sources=sorted({i.source for i, s in zip(items, split, strict=True) if s == "test"}),
        held_out_items_outside_test=sum(
            1 for i, s in zip(items, split, strict=True) if i.source == held_out and s != "test"
        ),
        other_items_in_test=sum(
            1 for i, s in zip(items, split, strict=True) if i.source != held_out and s == "test"
        ),
        excluded=sum(1 for s in split if s == EXCLUDED),
    )


def linked_training_items(split: Sequence[str], groups: Sequence[str]) -> int:
    """Training or validation items whose constraint group also has a test item."""
    in_test = {g for g, s in zip(groups, split, strict=True) if s == "test"}
    return sum(
        1 for g, s in zip(groups, split, strict=True) if s in ("train", "val") and g in in_test
    )
