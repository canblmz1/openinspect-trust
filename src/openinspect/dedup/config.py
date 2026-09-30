"""The audit configuration (``configs/dedup.yaml``): pinned model weights and preprocessing."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import yaml
from pydantic import Field, ValidationError, model_validator

from openinspect.provenance.schema import Sha256, StrictModel

CONFIG_PATH = Path("configs") / "dedup.yaml"
REVISION_RE = r"^[0-9a-f]{40}$"


class ConfigError(Exception):
    """The audit configuration is missing or invalid."""


class ModelEntry(StrictModel):
    model_id: str = Field(min_length=3)
    revision: Annotated[str, Field(pattern=REVISION_RE)]  # a commit id, never a branch name
    weights_file: str = Field(min_length=1)
    weights_sha256: Sha256
    dim: int = Field(gt=0)
    licence: str


class Preprocessing(StrictModel):
    version: str = Field(min_length=1)


class DedupConfig(StrictModel):
    schema_version: int
    preprocessing: Preprocessing
    backend: str = Field(min_length=1)
    default_model: str
    models: dict[str, ModelEntry]

    @model_validator(mode="after")
    def _default_exists(self) -> DedupConfig:
        if self.default_model not in self.models:
            raise ValueError(f"default_model {self.default_model!r} is not in models")
        return self

    def model(self, name: str | None = None) -> tuple[str, ModelEntry]:
        key = name or self.default_model
        entry = self.models.get(key)
        if entry is None:
            raise ConfigError(
                f"unknown model {key!r}; choose one of {', '.join(sorted(self.models))}"
            )
        return key, entry


def load_config(repo_root: Path) -> DedupConfig:
    path = repo_root / CONFIG_PATH
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"cannot read {CONFIG_PATH.as_posix()}: {exc}") from exc
    try:
        return DedupConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"invalid {CONFIG_PATH.as_posix()}: {exc}") from exc
