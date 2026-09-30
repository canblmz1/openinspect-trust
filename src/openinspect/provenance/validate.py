"""Rules that need data outside one manifest: the licence allowlist and the evidence archive."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Collection, Sequence
from pathlib import Path
from typing import Literal

from openinspect.provenance.licences import LicenceAllowlist
from openinspect.provenance.registry import Issue, LoadedManifest, Registry
from openinspect.provenance.schema import SourceManifest

Release = Literal["internal", "public"]

EVIDENCE_DIR = Path("manifests") / "evidence"
INDEX_NAME = "SHA256SUMS.txt"
INDEX_PATH = (EVIDENCE_DIR / INDEX_NAME).as_posix()
_INDEX_LINE = re.compile(r"([0-9a-f]{64})  (\S.*)")
_NOT_EVIDENCE = {".gitkeep", INDEX_NAME}


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(chunk_size):
            digest.update(block)
    return digest.hexdigest()


def validate_manifest(
    manifest: SourceManifest, *, allowlist: LicenceAllowlist, release: Release = "internal"
) -> list[Issue]:
    """Allowlist and public-release rules for one manifest (no disk access)."""
    if manifest.status != "accepted":
        return []
    slug = manifest.slug
    issues: list[Issue] = []
    spdx = manifest.licence.spdx
    if spdx is not None and not allowlist.is_allowed(spdx):
        reason = allowlist.blocked_reason(spdx)
        detail = f"{reason}; " if reason else ""
        issues.append(
            Issue(
                "error",
                "E_LICENCE_NOT_ALLOWED",
                f"licence {spdx} is not on the allowlist ({detail}see configs/licences.yaml)",
                slug,
                "licence.spdx",
            )
        )
    blockers = manifest.public_release_blockers()
    if blockers:
        public = release == "public"
        issues.append(
            Issue(
                "error" if public else "warning",
                "E_PUBLIC_RELEASE_BLOCKED" if public else "W_PUBLIC_RELEASE_BLOCKED",
                "public release is blocked: " + "; ".join(blockers),
                slug,
                "licence",
            )
        )
    return issues


def read_evidence_index(root: Path) -> tuple[dict[str, str] | None, list[Issue]]:
    """Parse ``SHA256SUMS.txt`` into ``{repo-relative path: sha256}`` (``None`` when absent)."""
    path = root / INDEX_PATH
    if not path.is_file():
        return None, []
    index: dict[str, str] = {}
    issues: list[Issue] = []
    text = path.read_text(encoding="ascii", errors="replace")
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        match = _INDEX_LINE.fullmatch(line)
        if match is None:
            issues.append(
                Issue(
                    "error",
                    "E_EVIDENCE_INDEX_MALFORMED",
                    f"line {number} is not '<sha256>  <path>'",
                    None,
                    INDEX_PATH,
                )
            )
            continue
        index[(EVIDENCE_DIR / match.group(2)).as_posix()] = match.group(1)
    return index, issues


def verify_evidence(
    root: Path, loaded: Sequence[LoadedManifest], *, whole_archive: bool
) -> list[Issue]:
    """Check archived evidence files against the manifests and against ``SHA256SUMS.txt``.

    With ``whole_archive`` the index itself is audited too: entries without a file, files without an
    entry, and files no manifest refers to.
    """
    issues: list[Issue] = []
    referenced: dict[str, tuple[str, str]] = {}
    for item in loaded:
        for evidence in item.manifest.licence.evidence:
            if evidence.archived_path and evidence.sha256:
                referenced.setdefault(evidence.archived_path, (evidence.sha256, item.manifest.slug))
    index, index_issues = read_evidence_index(root)
    issues.extend(index_issues)
    if referenced and index is None:
        issues.append(
            Issue(
                "error",
                "E_EVIDENCE_INDEX_MISSING",
                f"{INDEX_PATH} is missing but manifests refer to archived evidence",
                None,
                INDEX_PATH,
            )
        )
    for path, (claimed, slug) in sorted(referenced.items()):
        file = root / path
        if not file.is_file():
            issues.append(
                Issue(
                    "error",
                    "E_EVIDENCE_MISSING_FILE",
                    f"archived evidence {path} does not exist",
                    slug,
                    path,
                )
            )
            continue
        actual = sha256_file(file)
        if actual != claimed:
            issues.append(
                Issue(
                    "error",
                    "E_EVIDENCE_HASH_MISMATCH",
                    f"{path}: the manifest records {claimed[:12]}..., "
                    f"the file hashes to {actual[:12]}...",
                    slug,
                    path,
                )
            )
        if index is not None:
            listed = index.get(path)
            if listed is None:
                issues.append(
                    Issue(
                        "error",
                        "E_EVIDENCE_NOT_INDEXED",
                        f"{path} is not listed in {INDEX_NAME}",
                        slug,
                        path,
                    )
                )
            elif listed != actual:
                issues.append(
                    Issue(
                        "error",
                        "E_EVIDENCE_INDEX_MISMATCH",
                        f"{path}: {INDEX_NAME} lists {listed[:12]}..., "
                        f"the file hashes to {actual[:12]}...",
                        slug,
                        path,
                    )
                )
    if whole_archive and index is not None:
        issues.extend(_audit_archive(root, index, referenced))
    return issues


def _audit_archive(root: Path, index: dict[str, str], referenced: Collection[str]) -> list[Issue]:
    issues: list[Issue] = []
    for path in sorted(index):
        if not (root / path).is_file():
            issues.append(
                Issue(
                    "error",
                    "E_EVIDENCE_INDEX_ORPHAN",
                    f"{INDEX_NAME} lists {path}, which does not exist",
                    None,
                    path,
                )
            )
    evidence_root = root / EVIDENCE_DIR
    if evidence_root.is_dir():
        for file in sorted(evidence_root.rglob("*")):
            if not file.is_file() or file.name in _NOT_EVIDENCE:
                continue
            rel = file.relative_to(root).as_posix()
            if rel not in index:
                issues.append(
                    Issue(
                        "warning",
                        "W_EVIDENCE_UNINDEXED",
                        f"{rel} is not listed in {INDEX_NAME}",
                        None,
                        rel,
                    )
                )
            elif rel not in referenced:
                issues.append(
                    Issue(
                        "warning",
                        "W_EVIDENCE_UNREFERENCED",
                        f"{rel} is not referenced by any manifest",
                        None,
                        rel,
                    )
                )
    return issues


def validate_registry(
    registry: Registry,
    allowlist: LicenceAllowlist,
    *,
    check_evidence: bool = True,
    release: Release = "internal",
    only: Sequence[str] | None = None,
) -> list[Issue]:
    """Everything that can be wrong with the registry (or with the sources named in ``only``)."""
    issues: list[Issue] = []
    selected = list(registry.loaded)
    if only is None:
        issues.extend(registry.issues)
    else:
        wanted = set(only)
        for slug in sorted(wanted - set(registry.slugs)):
            issues.append(Issue("error", "E_UNKNOWN_SLUG", f"no source with slug {slug!r}", slug))
        selected = [item for item in selected if item.manifest.slug in wanted]
        issues.extend(issue for issue in registry.issues if issue.slug in wanted)
    for item in selected:
        issues.extend(validate_manifest(item.manifest, allowlist=allowlist, release=release))
    if check_evidence:
        issues.extend(verify_evidence(registry.root, selected, whole_archive=only is None))
    return issues
