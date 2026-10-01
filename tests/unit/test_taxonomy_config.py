"""The taxonomy configuration: statuses, references, benchmark classes, coverage of the sources."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from openinspect.taxonomy.config import (
    TAXONOMY_PATH,
    LabelMapping,
    Taxonomy,
    TaxonomyError,
    check_against_sources,
    load_taxonomy,
)
from tests.dedup_helpers import REPO_ROOT
from tests.taxonomy_helpers import DECLARED, taxonomy, taxonomy_data


def test_a_rejected_label_has_no_normalized_label() -> None:
    with pytest.raises(ValidationError, match="REJECTED label has no normalized label"):
        LabelMapping(normalized_label="short", status="REJECTED", evidence="a placeholder class")


@pytest.mark.parametrize("status", ["EXACT", "COMPATIBLE", "SOURCE_SPECIFIC"])
def test_every_other_status_needs_a_normalized_label(status: str) -> None:
    with pytest.raises(ValidationError, match="needs a normalized label"):
        LabelMapping.model_validate(
            {"normalized_label": None, "status": status, "evidence": "some long evidence"}
        )


def test_an_ambiguous_mapping_names_its_candidate_and_only_it_may() -> None:
    with pytest.raises(ValidationError, match="names its candidate"):
        LabelMapping(normalized_label="burr", status="AMBIGUOUS", evidence="burrs at the edges")
    with pytest.raises(ValidationError, match="only an AMBIGUOUS mapping has a candidate"):
        LabelMapping(
            normalized_label="short", status="EXACT", evidence="the same thing", candidate="open"
        )


def test_evidence_is_required() -> None:
    with pytest.raises(ValidationError):
        LabelMapping(normalized_label="short", status="EXACT", evidence="short")


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            {
                "classes": {
                    "short": {"family": "nowhere", "definition": "a connection of conductors"}
                }
            },
            "unknown family",
        ),
        ({"citations": {"src-a": "Paper A"}}, "has no citation"),
    ],
)
def test_references_must_resolve(change: dict[str, Any], message: str) -> None:
    data = taxonomy_data(**change)
    with pytest.raises(ValidationError, match=message):
        Taxonomy.model_validate(data)


def test_a_mapping_must_target_a_known_class() -> None:
    data = taxonomy_data()
    data["mappings"]["src-a"]["SH"]["normalized_label"] = "bridge"
    with pytest.raises(ValidationError, match="unknown class 'bridge'"):
        Taxonomy.model_validate(data)
    data = taxonomy_data()
    data["mappings"]["src-b"]["burr"]["candidate"] = "whisker"
    with pytest.raises(ValidationError, match="unknown class 'whisker'"):
        Taxonomy.model_validate(data)


def test_benchmark_classes_are_those_every_source_reaches_comparably() -> None:
    t = taxonomy()
    # spur: EXACT in src-a, only an AMBIGUOUS candidate in src-b; hole: source-specific
    assert t.benchmark_classes == ["short", "open"]
    assert Taxonomy.model_validate(taxonomy_data(mappings={})).benchmark_classes == []


def test_the_mapping_can_be_reversed_per_source() -> None:
    t = taxonomy()
    assert t.original_labels("src-a", "short") == ["SH"]
    assert t.original_labels("src-b", "burr") == ["burr"]
    assert t.original_labels("src-b", "spur") == []  # a candidate is not a mapping
    assert t.original_labels("unknown", "short") == []


def test_an_unmapped_label_is_an_error() -> None:
    with pytest.raises(TaxonomyError, match="src-a:XX has no mapping"):
        taxonomy().mapping("src-a", "XX")


def test_coverage_of_the_sources() -> None:
    t = taxonomy()
    used = {"src-a": ["SH", "OP"], "src-b": ["short", "burr"]}
    assert check_against_sources(t, DECLARED, used) == []
    problems = check_against_sources(
        t,
        {"src-a": [*DECLARED["src-a"], "NEW"], "src-b": DECLARED["src-b"], "src-c": ["x"]},
        {"src-a": ["SH"], "src-b": ["placeholder"]},
    )
    assert problems == [
        "src-a:NEW is not mapped",
        "src-b:placeholder is REJECTED but annotations use it",
        "src-c: no mappings",
    ]
    undeclared = check_against_sources(t, {"src-a": ["SH", "OP", "SP"]}, {})
    assert undeclared == ["src-a:HB is mapped but the manifest does not declare it"]


def test_load_taxonomy_reports_missing_malformed_and_invalid_files(tmp_path: Path) -> None:
    with pytest.raises(TaxonomyError, match="cannot read"):
        load_taxonomy(tmp_path)
    path = tmp_path / TAXONOMY_PATH
    path.parent.mkdir(parents=True)
    path.write_text("schema_version: [1", encoding="utf-8")
    with pytest.raises(TaxonomyError, match="cannot read"):
        load_taxonomy(tmp_path)
    path.write_text(yaml.safe_dump({"schema_version": 2}), encoding="utf-8")
    with pytest.raises(TaxonomyError, match="invalid"):
        load_taxonomy(tmp_path)
    path.write_text(yaml.safe_dump(taxonomy_data(), sort_keys=False), encoding="utf-8")
    assert load_taxonomy(tmp_path).benchmark_classes == ["short", "open"]


def test_the_committed_taxonomy() -> None:
    t = load_taxonomy(REPO_ROOT)
    assert t.benchmark_classes == ["short", "open", "mouse_bite", "spurious_copper"]
    statuses = {m.status for labels in t.mappings.values() for m in labels.values()}
    assert statuses == {"EXACT", "COMPATIBLE", "AMBIGUOUS", "SOURCE_SPECIFIC", "REJECTED"}
    # names alone never decide: the same-named "scratch" is COMPATIBLE, not a benchmark class
    assert t.mapping("pcb-ind", "scratch").status == "COMPATIBLE"
    assert t.mapping("pcb-ind", "copper_burr").candidate == "spur"
    assert t.label_quality.size_outlier_z == pytest.approx(3.5)
