"""The taxonomy configuration (``configs/taxonomy.yaml``) and its validation (M4)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, ValidationError, model_validator

from openinspect.provenance.schema import StrictModel

TAXONOMY_PATH = Path("configs") / "taxonomy.yaml"
Status = Literal["EXACT", "COMPATIBLE", "AMBIGUOUS", "SOURCE_SPECIFIC", "REJECTED"]
COMPARABLE: tuple[Status, ...] = ("EXACT", "COMPATIBLE")


class TaxonomyError(Exception):
    """The taxonomy configuration is missing, malformed or inconsistent."""


class Hierarchy(StrictModel):
    level_0: str = Field(min_length=1)
    families: dict[str, str]


class ClassDefinition(StrictModel):
    family: str
    definition: str = Field(min_length=10)


class LabelMapping(StrictModel):
    """How one original label maps onto the normalized taxonomy."""

    normalized_label: str | None
    status: Status
    evidence: str = Field(min_length=10)
    candidate: str | None = None  # for AMBIGUOUS: the normalized class it might belong to

    @model_validator(mode="after")
    def _consistent(self) -> LabelMapping:
        if self.status == "REJECTED":
            if self.normalized_label is not None:
                raise ValueError("a REJECTED label has no normalized label")
        elif self.normalized_label is None:
            raise ValueError(f"a {self.status} mapping needs a normalized label")
        if self.status == "AMBIGUOUS" and self.candidate is None:
            raise ValueError("an AMBIGUOUS mapping names its candidate class")
        if self.status != "AMBIGUOUS" and self.candidate is not None:
            raise ValueError("only an AMBIGUOUS mapping has a candidate")
        return self


class ConsideredMerge(StrictModel):
    labels: list[str] = Field(min_length=2)
    decision: str
    reason: str = Field(min_length=10)


class QualityRules(StrictModel):
    """Declared rules of the label-quality checks: a rule flags a box for review, never changes it."""

    min_box_side_px: float = Field(default=2.0, gt=0)
    max_aspect_ratio: float = Field(default=20.0, gt=1)
    same_box_iou: float = Field(default=0.9, gt=0, le=1)
    size_outlier_z: float = Field(default=3.5, gt=0)
    informational_flags: list[str] = Field(default_factory=lambda: ["no_annotations"])


class Taxonomy(StrictModel):
    schema_version: Literal[1]
    hierarchy: Hierarchy
    classes: dict[str, ClassDefinition]
    citations: dict[str, str]
    mappings: dict[str, dict[str, LabelMapping]]
    considered_merges: list[ConsideredMerge] = Field(default_factory=list)
    label_quality: QualityRules = Field(default_factory=QualityRules)

    @model_validator(mode="after")
    def _references(self) -> Taxonomy:
        for name, entry in self.classes.items():
            if entry.family not in self.hierarchy.families:
                raise ValueError(f"class {name!r} names an unknown family {entry.family!r}")
        for source, labels in self.mappings.items():
            if source not in self.citations:
                raise ValueError(f"source {source!r} has no citation")
            for label, mapping in labels.items():
                for target in (mapping.normalized_label, mapping.candidate):
                    if target is not None and target not in self.classes:
                        raise ValueError(f"{source}:{label} maps to an unknown class {target!r}")
        return self

    def mapping(self, source: str, label: str) -> LabelMapping:
        try:
            return self.mappings[source][label]
        except KeyError as exc:
            raise TaxonomyError(
                f"{source}:{label} has no mapping in {TAXONOMY_PATH.as_posix()}"
            ) from exc

    @property
    def benchmark_classes(self) -> list[str]:
        """Normalized classes that every source reaches with an EXACT or COMPATIBLE mapping."""
        reached: list[set[str]] = [
            {
                m.normalized_label
                for m in labels.values()
                if m.status in COMPARABLE and m.normalized_label
            }
            for labels in self.mappings.values()
        ]
        if not reached:
            return []
        common = set.intersection(*reached)
        return [name for name in self.classes if name in common]  # in the configured order

    def original_labels(self, source: str, normalized: str) -> list[str]:
        """The inverse mapping: the original labels of ``source`` behind a normalized label."""
        return sorted(
            label
            for label, m in self.mappings.get(source, {}).items()
            if m.normalized_label == normalized
        )


def load_taxonomy(repo_root: Path) -> Taxonomy:
    path = repo_root / TAXONOMY_PATH
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise TaxonomyError(f"cannot read {TAXONOMY_PATH.as_posix()}: {exc}") from exc
    try:
        return Taxonomy.model_validate(raw)
    except ValidationError as exc:
        raise TaxonomyError(f"invalid {TAXONOMY_PATH.as_posix()}: {exc}") from exc


def check_against_sources(
    taxonomy: Taxonomy, declared: Mapping[str, Sequence[str]], used: Mapping[str, Sequence[str]]
) -> list[str]:
    """Problems with the coverage of the mapping; an empty list means it is complete.

    ``declared`` holds the class labels each source manifest lists, ``used`` the labels that occur
    in the annotation records. Every declared or used label must be mapped, a used label must not
    be REJECTED, and a mapped label that no source declares must be REJECTED (a placeholder).
    """
    problems: list[str] = []
    for source in sorted(set(declared) | set(used)):
        labels = taxonomy.mappings.get(source)
        if labels is None:
            problems.append(f"{source}: no mappings")
            continue
        for label in sorted(set(declared.get(source, ())) | set(used.get(source, ()))):
            if label not in labels:
                problems.append(f"{source}:{label} is not mapped")
        for label in sorted(set(used.get(source, ()))):
            if label in labels and labels[label].status == "REJECTED":
                problems.append(f"{source}:{label} is REJECTED but annotations use it")
        for label, mapping in sorted(labels.items()):
            if label not in declared.get(source, ()) and mapping.status != "REJECTED":
                problems.append(f"{source}:{label} is mapped but the manifest does not declare it")
    return problems
