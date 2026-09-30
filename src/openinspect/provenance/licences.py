"""The licence allowlist (``configs/licences.yaml``)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, ValidationError

from openinspect.provenance.schema import Spdx, StrictModel, Url


class LicenceConfigError(Exception):
    """The allowlist file is missing or malformed."""


class AllowedLicence(StrictModel):
    spdx: Spdx
    name: str = Field(min_length=1)
    url: Url


class BlockedTerm(StrictModel):
    token: str = Field(min_length=1)
    meaning: str = Field(min_length=1)


class LicenceAllowlist(StrictModel):
    schema_version: Literal[1]
    allowlist: list[AllowedLicence] = Field(min_length=1)
    blocked_terms: list[BlockedTerm] = Field(default_factory=list)

    def is_allowed(self, spdx: str) -> bool:
        """SPDX ids are compared case-insensitively."""
        return any(item.spdx.lower() == spdx.lower() for item in self.allowlist)

    def blocked_reason(self, spdx: str) -> str | None:
        """Why an SPDX id is refused outright (NC, ND, SA ...), or ``None``."""
        tokens = {token.upper() for token in spdx.split("-")}
        reasons = [term.meaning for term in self.blocked_terms if term.token.upper() in tokens]
        return ", ".join(reasons) if reasons else None


def load_allowlist(path: Path) -> LicenceAllowlist:
    """Read and validate the allowlist; any problem raises :class:`LicenceConfigError`."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise LicenceConfigError(
            f"cannot read the licence allowlist {path}: {exc.strerror or exc}"
        ) from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise LicenceConfigError(f"invalid YAML in the licence allowlist {path}: {exc}") from exc
    try:
        return LicenceAllowlist.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(part) for part in first["loc"]) or "<file>"
        raise LicenceConfigError(
            f"invalid licence allowlist {path}: {where}: {first['msg']} "
            f"({exc.error_count()} error(s))"
        ) from exc
