"""The human-validation status is read from the review queue itself."""

from __future__ import annotations

from pathlib import Path

import pytest

from openinspect.validation import (
    SIMILARITY_LIMITATION,
    HumanValidation,
    QueueError,
    queue_label,
    read_queue,
    read_validation,
)
from tests.dedup_helpers import REPO_ROOT


def test_status_and_statement() -> None:
    none = HumanValidation(queue="q.csv", queued=300, reviewed=0)
    assert none.status == "NOT PERFORMED"
    assert none.statement == (
        "**Human validation: NOT PERFORMED.** Reviewed pairs: 0 / 300 (`q.csv`). "
        + SIMILARITY_LIMITATION
    )
    partial = HumanValidation(queue="q.csv", queued=300, reviewed=12)
    assert partial.status == "PARTIAL"
    assert SIMILARITY_LIMITATION in partial.statement
    done = HumanValidation(queue="q.csv", queued=3, reviewed=3)
    assert done.status == "COMPLETE"
    assert SIMILARITY_LIMITATION not in done.statement
    assert done.record()["limitation"] is None
    assert none.record() == {
        "status": "NOT PERFORMED",
        "queue": "q.csv",
        "reviewed": 0,
        "queued": 300,
        "limitation": SIMILARITY_LIMITATION,
    }


def test_read_queue_counts_decisions(tmp_path: Path) -> None:
    path = tmp_path / "queue.csv"
    path.write_text("pair_id,human_decision\nP1,\nP2,same\nP3,  \n", encoding="utf-8")
    assert read_queue(path, "queue.csv") == HumanValidation(queue="queue.csv", queued=3, reviewed=1)
    path.write_text("pair_id,notes\nP1,x\n", encoding="utf-8")
    with pytest.raises(QueueError, match="no 'human_decision' column"):
        read_queue(path, "queue.csv")
    path.write_text("", encoding="utf-8")
    with pytest.raises(QueueError, match="no 'human_decision' column"):
        read_queue(path, "queue.csv")
    with pytest.raises(QueueError, match="cannot read"):
        read_queue(tmp_path / "missing.csv", "missing.csv")


def test_queue_label(tmp_path: Path) -> None:
    assert queue_label(tmp_path / "a" / "q.csv", tmp_path) == "a/q.csv"
    assert queue_label(Path("/elsewhere/q.csv"), tmp_path) == "q.csv"


def test_the_committed_queue_has_no_human_decision() -> None:
    status = read_validation(REPO_ROOT)
    assert (status.queued, status.reviewed, status.status) == (300, 0, "NOT PERFORMED")
