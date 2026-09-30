"""Per-source adapters, written against the real file layouts (never against a guess)."""

from __future__ import annotations

from openinspect.ingest.adapters import dspcbsd_plus, pcb_defect, pcb_ind
from openinspect.ingest.adapters.base import AdapterSpec

ADAPTERS: dict[str, AdapterSpec] = {
    "dspcbsd-plus": dspcbsd_plus.SPEC,
    "pcb-defect": pcb_defect.SPEC,
    "pcb-ind": pcb_ind.SPEC,
}

__all__ = ["ADAPTERS"]
