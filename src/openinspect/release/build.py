"""Assemble a release: items, images, splits, measurements, invariants and the manifest.

The steps are pure functions of the ingest records, the taxonomy, the M3 artifacts, the release
configuration and the seed, except :func:`write_images`, which writes the released image files
under the data directory (outside the repository).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import PIL
from PIL import features

from openinspect.files import replace_bytes, sha256_bytes, sha256_file
from openinspect.provenance.records import ImageRecord
from openinspect.provenance.schema import SourceManifest
from openinspect.release.checks import (
    ImagePair,
    Invariant,
    Provenance,
    SplitMeasure,
    invariants,
    measure,
)
from openinspect.release.config import ReleaseConfig
from openinspect.release.crops import crop_png, open_image
from openinspect.release.groups import Constraint, constraints, group_keys, union_groups
from openinspect.release.manifest import (
    INTERPRETATION,
    ClassEntry,
    Counts,
    Generator,
    M3Limitations,
    ReleasedFile,
    ReleaseManifest,
    Sampling,
    SchemeEntry,
    SourceEntry,
    TaxonomyEntry,
    ValidationRecord,
)
from openinspect.release.pool import (
    Candidate,
    Exclusion,
    ReleaseError,
    build_candidates,
    quotas,
    sample,
)
from openinspect.release.splits import EXCLUDED, group_split, held_out_split, random_split
from openinspect.taxonomy.config import COMPARABLE, Taxonomy
from openinspect.taxonomy.mapping import MappedImage
from openinspect.validation import HumanValidation

METHODS = {
    "A0": "random within strata of (source, classes of the item); groups ignored on purpose",
    "A1": "whole groups (metadata group_id + M3 visual similarity components at each source's primary level + exact duplicates + crop parents), balanced per source and class",
    "B": "the held-out source is the test set; the other sources are split group-aware into train and val; training-source items that share a constraint with a held-out item (a visual similarity component across sources) are excluded",
}
M3_STATEMENTS = [
    "A visual similarity component is a machine-detected potential leakage group (embedding-based similarity finding), not proof that two images show the same object.",
    "The M3 thresholds rest on proxy metadata (the sources' own keys), synthetic transforms and DINOv2-small whole-image similarity; neither labelled pool reached precision 0.90, so the rule's F1 fallback fixed the family level.",
    "The robustness model (DINOv2-base) keeps the direction of the M3 findings but finds far fewer crossing components; A1 uses the primary model's components.",
    "Crops inherit the visual similarity component of their parent image; the components were computed on whole images resized to 224x224.",
]


@dataclass(frozen=True)
class Assembly:
    items: list[Candidate]
    excluded: list[Exclusion]
    available: dict[str, int]
    quotas: dict[str, int]


def assemble(images: Sequence[MappedImage], taxonomy: Taxonomy, config: ReleaseConfig) -> Assembly:
    """Candidates, the quotas and the seeded sample."""
    candidates, excluded = build_candidates(images, taxonomy, config)
    available = dict(sorted(Counter(c.source for c in candidates).items()))
    counts = quotas(available, config.max_source_share, config.size)
    chosen, dropped = sample(candidates, counts, config.seed)
    return Assembly(chosen, [*excluded, *dropped], available, counts)


def write_images(items: Sequence[Candidate], folder: Path) -> list[ReleasedFile]:
    """Write every released image; files of earlier builds that are not released are removed."""
    folder.mkdir(parents=True, exist_ok=True)
    files: dict[int, ReleasedFile] = {}
    crops: dict[Path, list[int]] = defaultdict(list)
    for index, item in enumerate(items):
        if item.crop is not None:
            crops[item.item.path].append(index)
            continue
        data = item.item.path.read_bytes()
        digest = sha256_bytes(data)
        if digest != item.item.sha256:
            raise ReleaseError(f"{item.source}:{item.item.item_id} changed since ingest")
        _store(folder / item.file_name, data, digest)
        files[index] = ReleasedFile(sha256=digest, sha256_pixels=None, bytes=len(data))
    for parent, indices in sorted(crops.items()):
        if sha256_file(parent) != items[indices[0]].item.sha256:
            raise ReleaseError(f"{parent.name} changed since ingest")
        image = open_image(parent)
        for index in indices:
            rect = items[index].crop
            assert rect is not None  # noqa: S101 - grouped above by having a crop
            data, pixels = crop_png(image, rect)
            digest = sha256_bytes(data)
            _store(folder / items[index].file_name, data, digest)
            files[index] = ReleasedFile(sha256=digest, sha256_pixels=pixels, bytes=len(data))
    keep = {item.file_name for item in items}
    for stale in folder.iterdir():
        if stale.is_file() and stale.name not in keep:
            stale.unlink()
    return [files[i] for i in range(len(items))]


def _store(path: Path, data: bytes, digest: str) -> None:
    if not path.is_file() or sha256_file(path) != digest:
        replace_bytes(path, data)


@dataclass(frozen=True)
class Splits:
    constraints: list[Constraint]
    groups: list[str]  # constraint-group key of every item
    schemes: dict[str, list[str]]


def derive_splits(
    items: Sequence[Candidate],
    sha256: Sequence[str],
    components: Mapping[tuple[str, str], str],
    config: ReleaseConfig,
) -> Splits:
    """A0, A1 and one B fold per source."""
    found = constraints(items, components, sha256)
    keys = group_keys(items, union_groups(len(items), found))
    ratios = config.splits.ratios
    schemes: dict[str, list[str]] = {
        "A0": random_split(items, ratios, config.seed),
        "A1": [s or EXCLUDED for s in group_split(items, keys, ratios, config.seed)],
    }
    for source in sorted({item.source for item in items}):
        schemes[f"B-{source}"] = held_out_split(
            items, keys, found, source, config.splits.held_out_val, config.seed
        )
    return Splits(found, keys, schemes)


def rebuild_reversed(
    items: Sequence[Candidate],
    sha256: Sequence[str],
    components: Mapping[tuple[str, str], str],
    config: ReleaseConfig,
) -> Callable[[], dict[str, list[str]]]:
    """For I6: derive the splits from the items in reverse order, aligned back to ``items``."""

    def rebuild() -> dict[str, list[str]]:
        again = derive_splits(items[::-1], list(sha256)[::-1], components, config)
        position = {item.global_id: k for k, item in enumerate(items[::-1])}
        return {
            name: [split[position[item.global_id]] for item in items]
            for name, split in again.schemes.items()
        }

    return rebuild


@dataclass(frozen=True)
class Checked:
    measures: dict[str, SplitMeasure]
    invariants: list[Invariant]


def check(
    items: Sequence[Candidate],
    files: Sequence[ReleasedFile],
    splits: Splits,
    *,
    pairs: Sequence[ImagePair],
    primary: Mapping[str, str],
    records: Mapping[tuple[str, str], ImageRecord],
    allowlist: set[str],
    benchmark: set[str],
    rebuild: Callable[[], Mapping[str, Sequence[str]]],
) -> Checked:
    sha = [f.sha256 for f in files]
    measures = {
        name: measure(items, split, splits.constraints, pairs, primary, sha)
        for name, split in splits.schemes.items()
    }
    provenance = [
        Provenance(
            source=item.source,
            source_item_id=item.item.item_id,
            source_url=records[item.item.key].source_url,
            licence=records[item.item.key].source_license,
            sha256_source=records[item.item.key].sha256_source,
        )
        for item in items
    ]
    found = invariants(
        items,
        splits.schemes,
        measures,
        provenance,
        allowlist=allowlist,
        benchmark=benchmark,
        rebuild=rebuild,
    )
    return Checked(measures, found)


def _kind(name: str) -> tuple[str, str | None]:
    if name == "A0":
        return "random", None
    if name == "A1":
        return "group_aware", None
    return "source_held_out", name.removeprefix("B-")


def _source_entries(
    assembly: Assembly,
    images: Sequence[MappedImage],
    manifests: Mapping[str, SourceManifest],
    primary: Mapping[str, str],
    config: ReleaseConfig,
) -> list[SourceEntry]:
    ingested = Counter(image.item.source for image in images)
    released = Counter(item.source for item in assembly.items)
    boxes = Counter(dict.fromkeys(released, 0))
    for item in assembly.items:
        boxes[item.source] += len(item.boxes)
    reasons: dict[str, Counter[str]] = defaultdict(Counter)
    for e in assembly.excluded:
        reasons[e.source][e.reason] += 1
    total = len(assembly.items)
    entries: list[SourceEntry] = []
    for source in sorted(ingested):
        m = manifests[source]
        acquisition = next((i.item.acquisition_id for i in images if i.item.source == source), None)
        entries.append(
            SourceEntry(
                source=source,
                dataset_name=m.dataset_name,
                version=m.identity.version,
                doi=m.identity.doi,
                official_url=m.identity.official_url,
                licence=m.licence.spdx or "",
                licence_url=m.licence.licence_url,
                attribution=m.licence.attribution_text,
                changes_must_be_indicated=m.licence.changes_must_be_indicated,
                archive_sha256=dict(m.acquisition.archive_sha256 or {}),
                acquisition_id=acquisition,
                primary_similarity_level=primary.get(source, "family"),
                crop_policy=config.crops.get(source),
                images_ingested=ingested[source],
                candidates=assembly.available.get(source, 0),
                released_images=released[source],
                released_boxes=boxes[source],
                share=released[source] / total if total else 0.0,
                exclusions=dict(sorted(reasons[source].items())),
            )
        )
    return entries


def _class_entries(items: Sequence[Candidate], taxonomy: Taxonomy) -> list[ClassEntry]:
    boxes: Counter[str] = Counter()
    holders: Counter[str] = Counter()
    for item in items:
        labels = [b.normalized_label for b in item.boxes]
        boxes.update(labels)
        holders.update(set(labels))
    entries: list[ClassEntry] = []
    for class_id, name in enumerate(taxonomy.benchmark_classes):
        originals: dict[str, list[str]] = {}
        statuses: dict[str, list[str]] = {}
        for source in sorted(taxonomy.mappings):
            labels = [
                label
                for label in taxonomy.original_labels(source, name)
                if taxonomy.mapping(source, label).status in COMPARABLE
            ]
            originals[source] = labels
            statuses[source] = sorted({taxonomy.mapping(source, label).status for label in labels})
        entries.append(
            ClassEntry(
                class_id=class_id,
                name=name,
                family=taxonomy.classes[name].family,
                original_labels=originals,
                statuses=statuses,
                released_boxes=boxes[name],
                released_images=holders[name],
            )
        )
    return entries


def notes(items: Sequence[Candidate], splits: Splits, checked: Checked) -> list[str]:
    """Facts of this build that qualify how the splits can be read, in a fixed order."""
    found: list[str] = []
    totals = Counter(item.source for item in items)
    largest: dict[str, int] = {}
    for (source, _), n in Counter(
        (item.source, key) for item, key in zip(items, splits.groups, strict=True)
    ).items():
        largest[source] = max(largest.get(source, 0), n)
    a1 = splits.schemes["A1"]
    for source in sorted(totals):
        missing = [
            s
            for s in ("train", "val", "test")
            if not any(i.source == source and x == s for i, x in zip(items, a1, strict=True))
        ]
        if missing:
            found.append(
                f"A1: `{source}` has no {' or '.join(missing)} items: its largest constraint group "
                f"holds {largest[source]:,} of its {totals[source]:,} items "
                f"({100 * largest[source] / totals[source]:.1f}%), and a group is never cut. Compare "
                "A0 and A1 per source."
            )
    for name, split in splits.schemes.items():
        if not name.startswith("B-"):
            continue
        excluded = Counter(i.source for i, s in zip(items, split, strict=True) if s == EXCLUDED)
        if excluded:
            found.append(
                f"{name}: "
                + ", ".join(f"{n:,} `{s}` items" for s, n in sorted(excluded.items()))
                + f" share a constraint with `{name.removeprefix('B-')}` (a visual similarity "
                "component across sources) and are excluded from training in this fold."
            )
    a1_pairs = checked.measures["A1"].pairs_train_test.get("REVIEW_REQUIRED", 0)
    if a1_pairs:
        found.append(
            f"A1: {a1_pairs:,} M3 pHash-only candidate pairs (REVIEW_REQUIRED, below the family "
            "cosine) lie across train and test; the M3 protocol does not make them a similarity "
            "level, so they are measured, not used as constraints."
        )
    return found


@dataclass(frozen=True)
class ManifestContext:
    """Everything the manifest records that is not computed from the items."""

    version_dir: str  # e.g. "manifests/splits/v0.1"
    images_dir: str
    config_sha256: str
    taxonomy_path: str
    taxonomy_sha256: str
    code_commit: str | None
    code_dirty: bool | None
    validation: HumanValidation
    inputs: dict[str, str]


def build_manifest(
    assembly: Assembly,
    images: Sequence[MappedImage],
    splits: Splits,
    checked: Checked,
    *,
    taxonomy: Taxonomy,
    config: ReleaseConfig,
    manifests: Mapping[str, SourceManifest],
    primary: Mapping[str, str],
    files: Mapping[str, str],
    split_files: Mapping[str, tuple[str, str, str]],
    context: ManifestContext,
) -> ReleaseManifest:
    """``split_files`` gives per scheme (csv path, its SHA-256, meta path)."""
    items = assembly.items
    by_class = Counter(b.normalized_label for item in items for b in item.boxes)
    schemes: list[SchemeEntry] = []
    for name, split in splits.schemes.items():
        kind, held_out = _kind(name)
        ratios = (
            dict(config.splits.ratios)
            if held_out is None
            else {"train": 1 - config.splits.held_out_val, "val": config.splits.held_out_val}
        )
        path, digest, meta = split_files[name]
        schemes.append(
            SchemeEntry(
                name=name,
                kind=kind,  # type: ignore[arg-type]
                held_out=held_out,
                method=METHODS[name if held_out is None else "B"],
                ratios=ratios,
                file=path,
                sha256=digest,
                meta_file=meta,
                counts=dict(sorted(Counter(split).items())),
                measure=checked.measures[name],
            )
        )
    return ReleaseManifest(
        version=config.version,
        seed=config.seed,
        generated_by=Generator(
            command="openinspect release build",
            code_commit=context.code_commit,
            code_dirty=context.code_dirty,
            pillow=PIL.__version__,
            libjpeg=features.version("jpg"),
        ),
        config_sha256=context.config_sha256,
        images_dir=context.images_dir,
        sources=_source_entries(assembly, images, manifests, primary, config),
        taxonomy=TaxonomyEntry(
            path=context.taxonomy_path,
            sha256=context.taxonomy_sha256,
            benchmark_classes=taxonomy.benchmark_classes,
            classes=_class_entries(items, taxonomy),
        ),
        sampling=Sampling(
            method="seeded sample per source, stratified by the set of normalized classes of each item (largest remainder); quotas keep every source at or below the share limit",
            max_source_share=config.max_source_share,
            size=config.size,
            negatives=config.negatives,
            available=assembly.available,
            quotas=assembly.quotas,
        ),
        counts=Counts(
            images=len(items),
            boxes=sum(len(item.boxes) for item in items),
            by_source=dict(sorted(Counter(item.source for item in items).items())),
            by_class={name: by_class[name] for name in taxonomy.benchmark_classes},
        ),
        canonical_split=config.splits.canonical,
        splits=schemes,
        interpretation=INTERPRETATION,
        notes=notes(items, splits, checked),
        invariants=checked.invariants,
        m3_limitations=M3Limitations(
            human_validation=ValidationRecord.model_validate(context.validation.record()),
            statements=M3_STATEMENTS,
        ),
        files=dict(sorted(files.items())),
        inputs=dict(sorted(context.inputs.items())),
    )
