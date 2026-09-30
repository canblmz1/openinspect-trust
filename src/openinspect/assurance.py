"""Dataset assurance: a dimensional report on whether a benchmark split may be optimistic.

There is no scalar score: nothing calibrates a number such as "83/100", so none is given. Each
dimension gets a status by an explicit rule, and every status carries the measurements it rests on.
The module is platform-agnostic and domain-agnostic: its inputs are the generic audit (M3) and the
provenance records of the registry and of ingest (M1, M2), whatever the images show and wherever a
model is trained later.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from openinspect.dedup.audit_models import Audit, SourceProvenance
from openinspect.ingest.report import SourceReport
from openinspect.provenance.licences import load_allowlist
from openinspect.provenance.registry import load_registry
from openinspect.provenance.validate import validate_registry

Status = Literal["PASS", "WARNING", "FAIL", "MISSING", "LOW", "OK", "N/A"]
OPTIMISTIC = "POTENTIALLY OPTIMISTIC"
NO_EVIDENCE = "NO EVIDENCE OF OPTIMISM FOUND"
NOT_ASSESSABLE = "NOT ASSESSABLE (no official split)"
DIVERSITY_MIN = 3  # distinct acquisition kinds below which source diversity is LOW

RULES: dict[str, str] = {
    "Provenance coverage": "PASS if ingest recorded every image the manifest declares (with source, licence and SHA-256); FAIL otherwise; MISSING without an ingest report.",
    "Licence evidence": "PASS if the licence is on the allowlist and every archived evidence file matches its recorded hash; FAIL otherwise.",
    "Archive integrity": "PASS if size, repository checksum and zip CRC-32 all matched at ingest; FAIL if one did not; MISSING without an ingest report.",
    "Exact duplicates": "PASS if no two files of the source are byte-identical; FAIL if an identical pair crosses a split; WARNING otherwise.",
    "Visual similarity leakage": "At the source's primary level (chaining rule): PASS if no visual similarity component crosses a split and no evaluation image has a training image at or above the threshold; WARNING otherwise. Never FAIL: visual similarity is not proof of shared content.",
    "Group split integrity": "For the source's own keys (proxy metadata): PASS if no key value occurs in two splits; FAIL if one does; MISSING if the source has no key.",
    "Independent source validation": "PASS only when a source-held-out evaluation (split B) exists; M3 runs no model, so it is MISSING.",
    "Source diversity": f"OK with at least {DIVERSITY_MIN} distinct acquisition kinds among the sources; LOW below; MISSING if the kinds are not declared.",
    "Cross-source overlap": "PASS if no pair of images from two sources reaches the family threshold; WARNING otherwise (sources may not be independent).",
}
ASSESSMENT_RULE = (
    f"{OPTIMISTIC} if, for a source with an official split, exact duplicates FAIL, group split "
    f"integrity FAILs or visual similarity leakage is a WARNING; {NOT_ASSESSABLE} for a source "
    f"without a split; {NO_EVIDENCE} otherwise. Without independent source validation no "
    "assessment says how the benchmark transfers to other data."
)


@dataclass(frozen=True)
class Dimension:
    name: str
    status: Status
    evidence: list[str]


@dataclass(frozen=True)
class SourceAssessment:
    source: str
    dimensions: list[Dimension]
    assessment: str
    reasons: list[str]

    def status(self, name: str) -> Status:
        return next(d.status for d in self.dimensions if d.name == name)


@dataclass(frozen=True)
class AssuranceReport:
    sources: list[SourceAssessment]
    pool: list[Dimension]
    assessment: str


def collect_provenance(
    repo_root: Path, slugs: Sequence[str], acquisition: Mapping[str, str | None]
) -> list[SourceProvenance]:
    """Provenance facts of ``slugs`` from the registry, the licence allowlist and the ingest reports."""
    registry = load_registry(repo_root)
    allowlist = load_allowlist(repo_root / "configs" / "licences.yaml")
    issues = validate_registry(registry, allowlist, only=list(slugs))
    out: list[SourceProvenance] = []
    for slug in sorted(slugs):
        loaded = registry.get(slug)
        if loaded is None:
            continue
        manifest = loaded.manifest
        path = repo_root / "manifests" / "ingest" / slug / "report.json"
        report = (
            SourceReport.model_validate_json(path.read_text(encoding="utf-8"))
            if path.is_file()
            else None
        )
        archive = report.archive if report is not None else None
        out.append(
            SourceProvenance(
                source=slug,
                licence=manifest.licence.spdx,
                evidence_files=len(manifest.licence.evidence),
                evidence_ok=not any(i.slug == slug and i.level == "error" for i in issues),
                archive_ok=None
                if archive is None
                else bool(archive.size_ok and archive.checksum_ok and archive.zip_crc_ok),
                images_expected=manifest.content.image_count,
                images_recorded=report.decode.decodable if report is not None else None,
                acquisition_id=acquisition.get(slug),
            )
        )
    return out


def _pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:.1f}%" if whole else "n/a"


def _provenance(p: SourceProvenance | None) -> list[Dimension]:
    if p is None:
        return [
            Dimension(name, "MISSING", ["no provenance record"])
            for name in ("Provenance coverage", "Licence evidence", "Archive integrity")
        ]
    if p.images_recorded is None or p.images_expected is None:
        coverage = Dimension("Provenance coverage", "MISSING", ["no ingest report"])
    else:
        coverage = Dimension(
            "Provenance coverage",
            "PASS" if p.images_recorded == p.images_expected else "FAIL",
            [f"{p.images_recorded:,} of {p.images_expected:,} declared images recorded at ingest"],
        )
    licence = Dimension(
        "Licence evidence",
        "PASS" if p.evidence_ok and p.evidence_files > 0 and p.licence else "FAIL",
        [
            f"licence {p.licence or 'unknown'}; {p.evidence_files} archived evidence files"
            + ("; hashes verified" if p.evidence_ok else "; the registry reports an error")
        ],
    )
    if p.archive_ok is None:
        archive = Dimension("Archive integrity", "MISSING", ["no ingest report"])
    else:
        archive = Dimension(
            "Archive integrity",
            "PASS" if p.archive_ok else "FAIL",
            ["size, repository checksum and CRC-32 matched" if p.archive_ok else "a check failed"],
        )
    return [coverage, licence, archive]


def _exact(audit: Audit, source: str) -> Dimension:
    counts = [
        c
        for c in audit.categories
        if c.scope == f"within:{source}" and c.category == "EXACT_DUPLICATE"
    ]
    pairs = sum(c.pairs for c in counts)
    crossing = sum(c.cross_split for c in counts)
    status: Status = "PASS" if pairs == 0 else ("FAIL" if crossing else "WARNING")
    return Dimension(
        "Exact duplicates",
        status,
        [
            f"{pairs:,} byte-identical pairs inside the source, {crossing:,} across a split; "
            f"{audit.cross_source.sha256_equal_pairs:,} identical pairs between sources"
        ],
    )


def _primary_level(audit: Audit, source: str) -> str:
    family = next((level for level in audit.levels if level.level == "family"), None)
    return "near" if family is not None and source in family.chained_sources else "family"


def _leakage(audit: Audit, source: str) -> Dimension:
    level_name = _primary_level(audit, source)
    level = next((lv for lv in audit.levels if lv.level == level_name), None)
    leak = None if level is None else next((x for x in level.leakage if x.source == source), None)
    if level is None or leak is None or not leak.has_splits:
        return Dimension("Visual similarity leakage", "N/A", ["no official split"])
    t = level.threshold
    evidence = [
        f"{leak.groups_crossing_any:,} visual similarity components at cosine >= {t:.4f} "
        f"({level_name} level) cross a split, holding {leak.affected_images:,} of "
        f"{leak.n_images:,} images ({_pct(leak.affected_images, leak.n_images)})"
    ]
    exposed = 0
    for row in leak.eval_neighbour:
        exposed += row.with_train_neighbour
        evidence.append(
            f"{row.with_train_neighbour:,} of {row.images:,} {row.split} images "
            f"({_pct(row.with_train_neighbour, row.images)}) have a training image at cosine >= {t:.4f}"
        )
    baseline = level.permutation.get(source)
    if baseline is not None:
        evidence.append(
            f"random splits of the same sizes give {baseline.null_mean:.1f} ± {baseline.null_sd:.1f} "
            f"crossing components (official: {baseline.observed:,})"
        )
    status: Status = "PASS" if leak.groups_crossing_any == 0 and exposed == 0 else "WARNING"
    return Dimension("Visual similarity leakage", status, evidence)


def _group_integrity(audit: Audit, source: str, has_split: bool) -> Dimension:
    if not has_split:
        return Dimension("Group split integrity", "N/A", ["no official split"])
    rows = [r for r in audit.metadata_integrity if r.source == source]
    if not rows:
        return Dimension(
            "Group split integrity",
            "MISSING",
            ["the source carries no group key; visual similarity components are the only proxy"],
        )
    evidence = [
        f"{r.key_name} ({r.key}): {r.crossing:,} of {r.values:,} values occur in two or more "
        f"splits ({r.images_in_crossing:,} images)"
        for r in rows
    ]
    return Dimension(
        "Group split integrity", "FAIL" if any(r.crossing for r in rows) else "PASS", evidence
    )


def _pool(audit: Audit) -> list[Dimension]:
    kinds: dict[str, list[str]] = {}
    for p in audit.provenance:
        if p.acquisition_id:
            kinds.setdefault(p.acquisition_id, []).append(p.source)
    if not kinds:
        diversity = Dimension("Source diversity", "MISSING", ["acquisition kinds not declared"])
    else:
        diversity = Dimension(
            "Source diversity",
            "OK" if len(kinds) >= DIVERSITY_MIN else "LOW",
            [
                f"{len(audit.provenance)} sources, {len(kinds)} acquisition kinds: "
                + "; ".join(f"{kind} ({', '.join(sorted(s))})" for kind, s in sorted(kinds.items()))
            ],
        )
    family = [e for e in audit.cross_source.edges if e.level == "family" and e.pairs]
    near = {
        (e.source_a, e.source_b): e.pairs for e in audit.cross_source.edges if e.level == "near"
    }
    overlap = Dimension(
        "Cross-source overlap",
        "WARNING" if family else "PASS",
        [
            f"{e.source_a} / {e.source_b}: {e.pairs:,} pairs at the family level "
            f"({near.get((e.source_a, e.source_b), 0):,} at the near level), "
            f"{e.images_a:,} and {e.images_b:,} images"
            for e in family
        ]
        or ["no pair of images from two sources reaches the family threshold"],
    )
    independent = Dimension(
        "Independent source validation",
        "MISSING",
        ["no source-held-out evaluation has been run; it is part of the experiments (M7)"],
    )
    return [independent, diversity, overlap]


def assess(audit: Audit) -> AssuranceReport:
    """Every dimension of every source, and of the pool, by the rules in :data:`RULES`."""
    provenance = {p.source: p for p in audit.provenance}
    sources: list[SourceAssessment] = []
    for counts in audit.run.sources:
        source = counts.source
        has_split = any(name != "none" for name in counts.splits)
        dimensions = [
            *_provenance(provenance.get(source)),
            _exact(audit, source),
            _leakage(audit, source),
            _group_integrity(audit, source, has_split),
        ]
        by_name = {d.name: d.status for d in dimensions}
        reasons = [
            name
            for name, bad in (
                ("Exact duplicates", by_name["Exact duplicates"] == "FAIL"),
                ("Group split integrity", by_name["Group split integrity"] == "FAIL"),
                ("Visual similarity leakage", by_name["Visual similarity leakage"] == "WARNING"),
            )
            if bad
        ]
        verdict = (OPTIMISTIC if reasons else NO_EVIDENCE) if has_split else NOT_ASSESSABLE
        sources.append(SourceAssessment(source, dimensions, verdict, reasons if has_split else []))
    overall = (
        OPTIMISTIC
        if any(s.assessment == OPTIMISTIC for s in sources)
        else (NO_EVIDENCE if any(s.assessment == NO_EVIDENCE for s in sources) else NOT_ASSESSABLE)
    )
    return AssuranceReport(sources, _pool(audit), overall)
