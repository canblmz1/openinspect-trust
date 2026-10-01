"""Re-check a committed release from its files alone (``openinspect release check``, run in CI).

No data directory is needed: the manifest, the item and box tables, the split files, the
configuration, the taxonomy and the committed M3 artifacts are enough to recompute the hashes and
the invariants I1 to I5 and I7 to I9 (I6 needs the build; I10 is checked when a package is made).
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

import pyarrow.parquet as pq
from pydantic import ValidationError

from openinspect.files import sha256_file
from openinspect.provenance.licences import LicenceConfigError, load_allowlist
from openinspect.release.checks import ImagePair, primary_pair, read_image_pairs
from openinspect.release.config import RELEASE_PATH, SPLITS
from openinspect.release.ids import ID_PATTERN
from openinspect.release.manifest import ANNOTATIONS, ITEMS, RELEASE, ReleaseManifest, read_manifest
from openinspect.release.splits import EXCLUDED
from openinspect.taxonomy.config import COMPARABLE

M3_PAIRS = "artifacts/m3/duplicate-pairs.parquet"
PROVENANCE = ("source", "source_item_id", "source_url", "licence", "sha256_source")


def release_dir(root: Path, version: str) -> Path:
    return root / "manifests" / "releases" / version


def _crossing(keys: Sequence[str | None], split: Sequence[str]) -> int:
    seen: dict[str, set[str]] = defaultdict(set)
    for key, name in zip(keys, split, strict=True):
        if key is not None and name != EXCLUDED:
            seen[key].add(name)
    return sum(1 for names in seen.values() if len(names) > 1)


def _pairs_crossing(
    rows: Sequence[Mapping[str, object]],
    split: Sequence[str],
    pairs: Sequence[ImagePair],
    primary: Mapping[str, str],
) -> int:
    by_image: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row, name in zip(rows, split, strict=True):
        if name != EXCLUDED:
            by_image[(str(row["source"]), str(row["source_item_id"]))].add(name)
    count = 0
    for pair in pairs:
        if not primary_pair(pair, primary):
            continue
        a = by_image.get((pair.source_a, pair.image_a), set())
        b = by_image.get((pair.source_b, pair.image_b), set())
        if a and b and not (len(a) == 1 and a == b):
            count += 1
    return count


def _read_split(path: Path) -> dict[str, str]:
    reader = csv.DictReader(io.StringIO(path.read_text(encoding="utf-8")))
    return {row["id"]: row["split"] for row in reader}


def verify_release(root: Path, version: str) -> tuple[ReleaseManifest | None, list[str]]:
    """The manifest and every problem found; an empty list means the release checks out."""
    folder = release_dir(root, version)
    try:
        manifest = read_manifest(folder / RELEASE)
    except (OSError, ValidationError) as exc:
        return None, [f"cannot read {RELEASE}: {exc}"]
    problems: list[str] = []
    for name, digest in manifest.files.items():
        path = folder / name
        if not path.is_file() or sha256_file(path) != digest:
            problems.append(f"{name} does not match its SHA-256 in {RELEASE}")
    for path, digest, what in (
        (root / RELEASE_PATH, manifest.config_sha256, "release configuration"),
        (root / manifest.taxonomy.path, manifest.taxonomy.sha256, "taxonomy"),
    ):
        if not path.is_file() or sha256_file(path) != digest:
            problems.append(f"the {what} changed since the release was built")
    if problems:
        return manifest, problems
    rows = pq.read_table(folder / ITEMS).to_pylist()
    boxes = pq.read_table(folder / ANNOTATIONS).to_pylist()
    ids = [str(r["global_id"]) for r in rows]
    if len(set(ids)) != len(ids) or not all(ID_PATTERN.match(i) for i in ids):
        problems.append("global ids are not unique or not well formed")
    if manifest.counts.images != len(rows) or manifest.counts.boxes != len(boxes):
        problems.append("the item or box counts differ from the manifest")
    schemes: dict[str, list[str]] = {}
    for entry in manifest.splits:
        path = root / entry.file
        if not path.is_file() or sha256_file(path) != entry.sha256:
            problems.append(f"{entry.file} does not match its SHA-256")
            continue
        assigned = _read_split(path)
        if sorted(assigned) != sorted(ids):
            problems.append(f"{entry.file} does not list exactly the released items")
            continue
        split = [assigned[i] for i in ids]
        if not set(split) <= {*SPLITS, EXCLUDED}:
            problems.append(f"{entry.file} uses an unknown split name")
        if split != [str(r[f"split_{entry.name}"]) for r in rows]:
            problems.append(f"{entry.file} disagrees with {ITEMS}")
        schemes[entry.name] = split
    problems += _invariants(root, manifest, rows, boxes, schemes)
    problems += [
        f"{inv.id} is {inv.status} in the manifest"
        for inv in manifest.invariants
        if inv.status != "PASS"
    ]
    return manifest, problems


def _invariants(
    root: Path,
    manifest: ReleaseManifest,
    rows: Sequence[Mapping[str, object]],
    boxes: Sequence[Mapping[str, object]],
    schemes: Mapping[str, Sequence[str]],
) -> list[str]:
    problems: list[str] = []
    sources = [str(r["source"]) for r in rows]
    for name, split in schemes.items():
        if name.startswith("B-"):
            train = {s for s, n in zip(sources, split, strict=True) if n in ("train", "val")}
            test = {s for s, n in zip(sources, split, strict=True) if n == "test"}
            if train & test or test != {name.removeprefix("B-")}:
                problems.append(f"I1: {name} mixes sources between training and test")
        if _crossing([str(r["sha256"]) for r in rows], split):
            problems.append(f"I2: a file SHA-256 occurs in two splits of {name}")
    primary = {s.source: s.primary_similarity_level for s in manifest.sources}
    pairs_path = root / M3_PAIRS
    if manifest.inputs.get(M3_PAIRS) != (sha256_file(pairs_path) if pairs_path.is_file() else None):
        problems.append(f"{M3_PAIRS} differs from the one the release was built with")
        pairs: list[ImagePair] = []
    else:
        pairs = read_image_pairs(pairs_path)
    groups = [None if r["group_id"] is None else f"{r['source']}:{r['group_id']}" for r in rows]
    similarity = [
        None if r["similarity_group_id"] is None else str(r["similarity_group_id"]) for r in rows
    ]
    parents = [
        None if r["crop_x_min"] is None else f"{r['source']}:{r['source_item_id']}" for r in rows
    ]
    for name, split in schemes.items():
        if name == "A0":
            continue
        if _crossing(groups, split):
            problems.append(f"I4: a metadata group crosses a split of {name}")
        if _crossing(similarity, split) or _pairs_crossing(rows, split, pairs, primary):
            problems.append(
                f"I5: a visual similarity component or primary-level pair crosses {name}"
            )
        if _crossing(parents, split):
            problems.append(f"crop parents cross a split of {name}")
    if any(not r[field] for r in rows for field in PROVENANCE):
        problems.append("I7: an item lacks a provenance field")
    try:
        allowlist = load_allowlist(root / "configs" / "licences.yaml")
    except LicenceConfigError as exc:
        problems.append(f"I8: {exc}")
    else:
        if not all(allowlist.is_allowed(str(r["licence"])) for r in rows):
            problems.append("I8: a licence is not on the allowlist")
    classes = manifest.taxonomy.benchmark_classes
    for b in boxes:
        label = str(b["normalized_label"])
        if (
            label not in classes
            or b["mapping_status"] not in COMPARABLE
            or b["class_id"] != classes.index(label)
        ):
            problems.append(f"I9: box {b['ann_id']} is not a benchmark class")
            break
    return problems
