"""The release configuration (``configs/release.yaml``)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, ValidationError, field_validator, model_validator

from openinspect.provenance.schema import StrictModel

RELEASE_PATH = Path("configs") / "release.yaml"
SPLITS = ("train", "val", "test")


class ReleaseConfigError(Exception):
    """The release configuration is missing or invalid."""


class SizeRange(StrictModel):
    min: int = Field(gt=0)
    max: int = Field(gt=0)

    @model_validator(mode="after")
    def _ordered(self) -> SizeRange:
        if self.min > self.max:
            raise ValueError("size.min must not exceed size.max")
        return self


class CropPolicy(StrictModel):
    """Square ROI crops around benchmark boxes, in native pixels (decision D7)."""

    min_side_px: int = Field(gt=0)
    margin: float = Field(ge=0, lt=0.5)  # the anchor box fills at most 1 - 2 * margin of the side
    format: Literal["png"] = "png"


def _in_split_order(value: object) -> object:
    """Train, val, test in that order, whatever order the file lists them in."""
    if isinstance(value, dict) and set(value) == set(SPLITS):
        return {name: value[name] for name in SPLITS}
    return value


class SplitConfig(StrictModel):
    ratios: dict[str, float]
    held_out_val: float = Field(gt=0, lt=1)
    canonical: Literal["A0", "A1"] = "A1"

    _order = field_validator("ratios", mode="before")(_in_split_order)

    @model_validator(mode="after")
    def _three_splits(self) -> SplitConfig:
        if tuple(self.ratios) != SPLITS or any(r <= 0 for r in self.ratios.values()):
            raise ValueError("ratios must give train, val and test, all positive")
        return self


class SmokeConfig(StrictModel):
    scheme: Literal["A0", "A1"] = "A1"
    counts: dict[str, int]

    _order = field_validator("counts", mode="before")(_in_split_order)

    @model_validator(mode="after")
    def _three_splits(self) -> SmokeConfig:
        if tuple(self.counts) != SPLITS or any(n <= 0 for n in self.counts.values()):
            raise ValueError("smoke counts must give train, val and test, all positive")
        return self


class ReleaseConfig(StrictModel):
    schema_version: Literal[1]
    version: str = Field(pattern=r"^v\d+\.\d+$")
    seed: int = Field(ge=0)
    size: SizeRange
    max_source_share: float = Field(gt=0, le=1)
    negatives: Literal["exclude", "include"] = "exclude"
    crops: dict[str, CropPolicy] = Field(default_factory=dict)
    splits: SplitConfig
    smoke: SmokeConfig


def load_release_config(repo_root: Path) -> ReleaseConfig:
    path = repo_root / RELEASE_PATH
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ReleaseConfigError(f"cannot read {RELEASE_PATH.as_posix()}: {exc}") from exc
    try:
        return ReleaseConfig.model_validate(raw)
    except ValidationError as exc:
        raise ReleaseConfigError(f"invalid {RELEASE_PATH.as_posix()}: {exc}") from exc
