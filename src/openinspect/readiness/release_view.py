"""A committed release rebuilt from its files, as the M5 build saw it (no data directory).

The release tables (``items.parquet``, ``annotations.parquet``), the M3 component table and the
release configuration are enough to rebuild every release item as a ``Candidate``, the grouping
constraints and the split schemes of M5. :func:`reproduce` re-derives the committed splits and the
group keys and reports any difference: the new regimes of M5.5 are built on the same footing only
when the old ones are reproduced exactly.
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import pyarrow.parquet as pq

from openinspect.dedup.inventory import ImageItem
from openinspect.release.checks import ImagePair, read_image_pairs
from openinspect.release.config import ReleaseConfig, load_release_config
from openinspect.release.groups import (
    Constraint,
    constraints,
    group_keys,
    read_components,
    union_groups,
)
from openinspect.release.manifest import ANNOTATIONS, ITEMS, RELEASE, ReleaseManifest, read_manifest
from openinspect.release.pool import Candidate, ReleaseBox
from openinspect.release.splits import EXCLUDED, group_split, held_out_split, random_split
from openinspect.release.verify import release_dir

M3_GROUPS = "artifacts/m3/leakage-groups.parquet"
M3_PAIRS = "artifacts/m3/duplicate-pairs.parquet"


class ViewError(Exception):
    """The committed release cannot be rebuilt or does not reproduce."""


@dataclass(frozen=True)
class ReleaseView:
    root: Path
    config: ReleaseConfig
    manifest: ReleaseManifest
    rows: list[dict[str, object]]  # items.parquet, in file order
    items: list[Candidate]  # the same order
    sha256: list[str]  # the released file of every item
    primary: dict[str, str]  # source -> primary M3 level
    components: dict[tuple[str, str], str]  # (source, image) -> M3 component at the primary level
    constraints: list[Constraint]
    groups: list[str]  # constraint-group key of every item
    schemes: dict[str, list[str]]  # committed split schemes, read from items.parquet
    pairs: list[ImagePair]

    @property
    def index(self) -> dict[str, int]:
        return {item.global_id: k for k, item in enumerate(self.items)}

    def split_file(self, name: str) -> Path:
        entry = next(e for e in self.manifest.splits if e.name == name)
        return self.root / entry.file


def _crop(row: Mapping[str, object]) -> tuple[int, int, int, int] | None:
    if row["crop_x_min"] is None:
        return None
    return (
        int(str(row["crop_x_min"])),
        int(str(row["crop_y_min"])),
        int(str(row["crop_x_max"])),
        int(str(row["crop_y_max"])),
    )


def _optional(value: object) -> str | None:
    return None if value is None else str(value)


def candidates_from_tables(
    rows: Sequence[Mapping[str, object]], boxes: Sequence[Mapping[str, object]]
) -> list[Candidate]:
    """Release items as ``Candidate`` objects; the item's path is its released file name."""
    by_item: dict[str, list[ReleaseBox]] = defaultdict(list)
    for b in boxes:
        by_item[str(b["global_id"])].append(
            ReleaseBox(
                source_ann_index=int(str(b["source_ann_index"])),
                original_label=str(b["original_label"]),
                normalized_label=str(b["normalized_label"]),
                mapping_status=str(b["mapping_status"]),
                class_id=int(str(b["class_id"])),
                bbox=(
                    float(str(b["x_min"])),
                    float(str(b["y_min"])),
                    float(str(b["x_max"])),
                    float(str(b["y_max"])),
                ),
                bbox_source=(
                    float(str(b["source_x_min"])),
                    float(str(b["source_y_min"])),
                    float(str(b["source_x_max"])),
                    float(str(b["source_y_max"])),
                ),
            )
        )
    items: list[Candidate] = []
    for r in rows:
        gid = str(r["global_id"])
        width, height = int(str(r["width"])), int(str(r["height"]))
        item = ImageItem(
            source=str(r["source"]),
            item_id=str(r["source_item_id"]),
            path=Path(PurePosixPath(str(r["file_name"]))),
            sha256=str(r["sha256_source"]),
            split=_optional(r["original_split"]),
            group_id=_optional(r["group_id"]),
            subgroup_id=_optional(r["subgroup_id"]),
            n_annotations=len(by_item[gid]),  # boxes of the released item, not of the original
            dhash=None,
            width=width,
            height=height,
            acquisition_id=_optional(r["acquisition_id"]),
        )
        items.append(
            Candidate(
                global_id=gid,
                item=item,
                crop=_crop(r),
                width=width,
                height=height,
                boxes=tuple(by_item[gid]),
            )
        )
    return items


def load_view(root: Path) -> ReleaseView:
    """The committed release of ``configs/release.yaml``, rebuilt from the repository's files."""
    config = load_release_config(root)
    folder = release_dir(root, config.version)
    try:
        manifest = read_manifest(folder / RELEASE)
        rows = pq.read_table(folder / ITEMS).to_pylist()
        boxes = pq.read_table(folder / ANNOTATIONS).to_pylist()
        primary = {s.source: s.primary_similarity_level for s in manifest.sources}
        components = read_components(root / M3_GROUPS, primary)
        pairs = read_image_pairs(root / M3_PAIRS)
    except (OSError, ValueError) as exc:
        raise ViewError(f"cannot read release {config.version}: {exc}") from exc
    items = candidates_from_tables(rows, boxes)
    sha = [str(r["sha256"]) for r in rows]
    found = constraints(items, components, sha)
    groups = group_keys(items, union_groups(len(items), found))
    schemes = {e.name: [str(r[f"split_{e.name}"]) for r in rows] for e in manifest.splits}
    return ReleaseView(
        root, config, manifest, rows, items, sha, primary, components, found, groups, schemes, pairs
    )


def read_split_csv(path: Path) -> dict[str, str]:
    reader = csv.DictReader(io.StringIO(path.read_text(encoding="utf-8")))
    return {row["id"]: row["split"] for row in reader}


@dataclass(frozen=True)
class Reproduction:
    """Whether the committed M5 outputs follow from the committed inputs."""

    group_keys_match: bool
    schemes_match: dict[str, bool]
    split_files_match: dict[str, bool]

    @property
    def ok(self) -> bool:
        return (
            self.group_keys_match
            and all(self.schemes_match.values())
            and all(self.split_files_match.values())
        )


def derive_m5(view: ReleaseView) -> dict[str, list[str]]:
    """A0, A1 and B-<source> exactly as ``openinspect release build`` derives them."""
    ratios = view.config.splits.ratios
    seed = view.config.seed
    out: dict[str, list[str]] = {
        "A0": random_split(view.items, ratios, seed),
        "A1": [s or EXCLUDED for s in group_split(view.items, view.groups, ratios, seed)],
    }
    for source in sorted({item.source for item in view.items}):
        out[f"B-{source}"] = held_out_split(
            view.items, view.groups, view.constraints, source, view.config.splits.held_out_val, seed
        )
    return out


def reproduce(view: ReleaseView) -> Reproduction:
    derived = derive_m5(view)
    files: dict[str, bool] = {}
    ids = [item.global_id for item in view.items]
    for name in view.schemes:
        assigned = read_split_csv(view.split_file(name))
        files[name] = [assigned.get(i) for i in ids] == view.schemes[name]
    return Reproduction(
        group_keys_match=view.groups == [str(r["constraint_group"]) for r in view.rows],
        schemes_match={name: derived.get(name) == split for name, split in view.schemes.items()},
        split_files_match=files,
    )
