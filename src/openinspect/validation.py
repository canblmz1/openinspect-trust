"""Whether the machine-generated similarity findings were validated by a person (decision T29).

The M3 thresholds rest on proxy metadata, synthetic transforms and an image representation. The
review queue that could validate them is kept, and every report or manifest that depends on the
similarity findings states how much of it was reviewed. The status is read from the queue file
itself, so a report cannot claim more than the file holds.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Literal

from pydantic import Field

from openinspect.provenance.schema import StrictModel

M3_QUEUE = "artifacts/m3/review-candidates.csv"
DECISION_COLUMN = "human_decision"
SIMILARITY_LIMITATION = (
    "The similarity findings have not yet been independently human-validated. Thresholds are "
    "based on proxy metadata, synthetic transforms and representation-based similarity."
)


class QueueError(Exception):
    """The review queue is missing or has no decision column."""


class HumanValidation(StrictModel):
    """How much of a review queue a person has decided."""

    queue: str = Field(min_length=1)  # repository path of the queue
    queued: int = Field(ge=0)
    reviewed: int = Field(ge=0)

    @property
    def status(self) -> Literal["NOT PERFORMED", "PARTIAL", "COMPLETE"]:
        if self.reviewed == 0:
            return "NOT PERFORMED"
        return "PARTIAL" if self.reviewed < self.queued else "COMPLETE"

    @property
    def statement(self) -> str:
        """One paragraph for a report: the status, the counts and, until complete, the limitation."""
        text = (
            f"**Human validation: {self.status}.** Reviewed pairs: {self.reviewed} / {self.queued} "
            f"(`{self.queue}`)."
        )
        return text if self.status == "COMPLETE" else f"{text} {SIMILARITY_LIMITATION}"

    def record(self) -> dict[str, object]:
        """The machine-readable form for manifests."""
        return {
            "status": self.status,
            "queue": self.queue,
            "reviewed": self.reviewed,
            "queued": self.queued,
            "limitation": None if self.status == "COMPLETE" else SIMILARITY_LIMITATION,
        }


def read_queue(path: Path, label: str) -> HumanValidation:
    """Count the rows of the queue at ``path`` and the rows with a non-empty human decision.

    ``label`` is how reports name the queue (its repository path), so they do not depend on where
    the repository is checked out.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise QueueError(f"cannot read the review queue {label}: {exc}") from exc
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or DECISION_COLUMN not in reader.fieldnames:
        raise QueueError(f"{label} has no {DECISION_COLUMN!r} column")
    rows = list(reader)
    reviewed = sum(1 for row in rows if (row.get(DECISION_COLUMN) or "").strip())
    return HumanValidation(queue=label, queued=len(rows), reviewed=reviewed)


def queue_label(path: Path, repo_root: Path) -> str:
    """The repository path of ``path``, or its file name when it lies outside the repository."""
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.name


def read_validation(repo_root: Path, queue: str = M3_QUEUE) -> HumanValidation:
    """The status of the committed queue ``queue`` (a repository path)."""
    return read_queue(repo_root / queue, queue)
