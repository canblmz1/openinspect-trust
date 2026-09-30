"""Builders for the manifest dictionaries and the licence config used across the tests."""

from __future__ import annotations

import copy
import hashlib
from datetime import date
from typing import Any

EVIDENCE_REL = "manifests/evidence/demo-source/record.json"
EVIDENCE_BYTES = b'{"license": "cc-by-4.0"}\n'
EVIDENCE_SHA = hashlib.sha256(EVIDENCE_BYTES).hexdigest()

LICENCES_YAML = """\
schema_version: 1
allowlist:
  - spdx: CC0-1.0
    name: Creative Commons Zero v1.0 Universal
    url: https://creativecommons.org/publicdomain/zero/1.0/
  - spdx: CC-BY-4.0
    name: Creative Commons Attribution 4.0 International
    url: https://creativecommons.org/licenses/by/4.0/
blocked_terms:
  - {token: NC, meaning: non-commercial terms}
  - {token: ND, meaning: no-derivatives terms}
  - {token: SA, meaning: share-alike terms}
"""


def accepted_manifest(slug: str = "demo-source") -> dict[str, Any]:
    """A complete, valid, accepted manifest; the `repo` fixture creates its evidence file."""
    return {
        "schema_version": 1,
        "slug": slug,
        "dataset_name": "Demo dataset",
        "status": "accepted",
        "decision": {
            "status": "accepted",
            "decided_by": "project-maintainer",
            "decided_on": date(2026, 9, 30),
            "evidence": [EVIDENCE_REL],
            "reason": "All admission gates pass.",
        },
        "identity": {
            "official_url": "https://zenodo.org/records/1",
            "doi": "10.5281/zenodo.1",
            "creators": ["Doe, Jane (Example University)"],
            "publisher_repository": "zenodo",
            "is_original_upload": True,
            "version": "v1",
            "published_on": date(2026, 1, 1),
        },
        "licence": {
            "spdx": "CC-BY-4.0",
            "licence_url": "https://creativecommons.org/licenses/by/4.0/",
            "stated_in": [{"where": "repository_record", "value": "licence CC BY 4.0"}],
            "redistribution": "allowed",
            "derivative_work": "allowed",
            "commercial_use": "allowed",
            "attribution_required": True,
            "attribution_text": "Doe, J. (2026). Demo dataset. Zenodo. CC BY 4.0.",
            "changes_must_be_indicated": True,
            "verified_on": date(2026, 9, 30),
            "evidence": [
                {
                    "kind": "repository_record_api",
                    "url": "https://zenodo.org/api/records/1",
                    "retrieved_on": date(2026, 9, 30),
                    "archived_path": EVIDENCE_REL,
                    "sha256": EVIDENCE_SHA,
                }
            ],
        },
        "content": {
            "domain": "demo",
            "task": "detection",
            "image_count": 10,
            "annotation_count": 20,
        },
    }


def pending_manifest(slug: str = "demo-pending") -> dict[str, Any]:
    return {"schema_version": 1, "slug": slug, "dataset_name": "Pending demo", "status": "pending"}


def rejected_manifest(slug: str = "demo-rejected") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "slug": slug,
        "dataset_name": "Rejected demo",
        "status": "rejected",
        "decision": {
            "status": "rejected",
            "decided_by": "project-maintainer",
            "decided_on": date(2026, 9, 30),
            "reason": "The licence is unclear.",
        },
    }


def with_value(data: dict[str, Any], dotted: str, value: object) -> dict[str, Any]:
    """Deep copy of ``data`` with ``dotted`` (e.g. ``"licence.spdx"``) set to ``value``."""
    result = copy.deepcopy(data)
    node = result
    *parents, leaf = dotted.split(".")
    for part in parents:
        node = node[part]
    node[leaf] = value
    return result
