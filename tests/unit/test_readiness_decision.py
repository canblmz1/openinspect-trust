"""The verdict rule, the limitations and the twelve answers, on the committed M5.5 numbers."""

from __future__ import annotations

from pathlib import Path

from openinspect.readiness.models import Readiness
from openinspect.readiness.narrative import answer_texts, limitations
from openinspect.readiness.pipeline import blockers, verdict
from openinspect.readiness.representation import RepresentationResult

REAL = Path(__file__).resolve().parents[2]


def committed() -> Readiness:
    return Readiness.model_validate_json(
        (REAL / "artifacts" / "m5_5" / "readiness.json").read_text(encoding="utf-8")
    )


def limits(
    r: Readiness, *, status: str | None = None, representation: RepresentationResult | None = None
) -> list[str]:
    return limitations(
        validation_status=status or str(r.human_validation["status"]),
        representation=representation or r.representation,
        giant=r.giant,
        designs=r.designs,
        labels=r.labels,
        negatives=r.negatives,
        phash=r.phash_only,
        probe=r.probe,
        held_out=r.held_out,
    )


def texts(r: Readiness, decided: str, blocking: list[str]) -> list[str]:
    return answer_texts(
        m6_verdict=r.m6_verdict,
        export=r.export,
        labels=r.labels,
        estimand=r.estimand,
        designs=r.designs,
        representation=r.representation,
        giant=r.giant,
        probe=r.probe,
        held_out=r.held_out,
        validation_status=str(r.human_validation["status"]),
        verdict=decided,
        blockers=blocking,
    )


def test_the_limitations_follow_from_the_numbers() -> None:
    r = committed()
    found = limits(r)
    assert found == r.limitations
    quiet = limits(
        r,
        status="COMPLETE",
        representation=r.representation.model_copy(
            update={"material": False, "material_reasons": []}
        ),
    )
    assert len(quiet) == len(found) - 2
    assert not [x for x in quiet if "Human validation" in x or "representation-sensitive" in x]


def test_the_last_answer_follows_the_verdict() -> None:
    r = committed()
    blocked = texts(r, "NOT TRAINING READY", ["x", "y"])
    assert blocked[-1] == "NOT TRAINING READY. No: x; y. The M7 plan is not executed."
    limited = texts(r, "TRAINING READY WITH EXPLICIT LIMITATIONS", [])
    assert "Yes, with the explicit limitations above" in limited[-1]
    ready = texts(r, "TRAINING READY", [])
    assert ready[-1].startswith("TRAINING READY. Yes, once the maintainer approves")
    assert len(ready) == 12
    assert ready[:-1] == limited[:-1] == blocked[:-1]


def test_every_blocker_condition_is_named_and_blocks() -> None:
    r = committed()
    design = r.designs[0]
    by = {c.name: c for c in design.conditions}
    broken = design.model_copy(
        update={
            "conditions": [
                by["C0"].model_copy(update={"exposed_test_items": 0}),
                by["C1"].model_copy(update={"exposed_test_items": 3}),
            ]
        }
    )
    mixed = r.held_out[0].model_copy(update={"pure": False})
    found = blockers(
        m6_verdict="FAIL",
        reproduced=False,
        exports_ok=False,
        fatal=2,
        designs=[broken],
        held_out=[mixed],
    )
    assert found == [
        "M6 verdict is FAIL",
        "the committed M5 splits do not reproduce from the committed inputs",
        "a package fails the independent export validation",
        "2 released boxes have invalid geometry (FATAL)",
        f"design {design.seed}: C1 leaves test items exposed",
        f"design {design.seed}: C0 exposes no test item",
        f"{mixed.regime} {mixed.fold} mixes sources between training and test",
    ]
    assert verdict(found, []) == "NOT TRAINING READY"
    assert verdict([], ["a limitation"]) == "TRAINING READY WITH EXPLICIT LIMITATIONS"
    assert verdict([], []) == "TRAINING READY"
    clean = blockers(
        m6_verdict="PASS",
        reproduced=True,
        exports_ok=True,
        fatal=0,
        designs=r.designs,
        held_out=r.held_out,
    )
    assert clean == []
