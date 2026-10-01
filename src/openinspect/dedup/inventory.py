"""The images of the ingested sources, with the metadata the audit needs (M3)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from openinspect.ingest.layout import source_dirs
from openinspect.provenance.records import ImageRecord


class InventoryError(Exception):
    """The ingest records are missing or unreadable."""


@dataclass(frozen=True)
class ImageItem:
    """One image in the generic form the audit works on; nothing here is specific to a domain.

    A source adapter decides what the keys mean for its source (``configs/dedup.yaml`` names
    them): ``group_id`` is the coarser unit images may share (a production batch, a design
    family, a patient), ``subgroup_id`` a finer one inside it, ``acquisition_id`` the kind of
    acquisition the source comes from. Any of them may be unknown.
    """

    source: str  # source id (the registry slug)
    item_id: str  # POSIX path inside the extracted archive
    path: Path
    sha256: str
    split: str | None
    group_id: str | None
    subgroup_id: str | None
    n_annotations: int
    dhash: int | None  # 64-bit difference hash from ingest
    width: int | None
    height: int | None
    acquisition_id: str | None = None
    flags: tuple[str, ...] = ()  # ingest flags of the image record

    @property
    def key(self) -> tuple[str, str]:
        return (self.source, self.item_id)


@dataclass(frozen=True)
class Unreadable:
    source: str
    item_id: str
    sha256: str
    stage: str
    error: str


def load_items(
    data_dir: Path, slugs: list[str], *, acquisition: Mapping[str, str | None] | None = None
) -> tuple[list[ImageItem], list[Unreadable]]:
    """Images of ``slugs`` in a fixed order (source, item id); images ingest could not decode are listed apart.

    ``acquisition`` gives the acquisition id of each source (``configs/dedup.yaml``), if known.
    """
    acquisition = acquisition or {}
    items: list[ImageItem] = []
    skipped: list[Unreadable] = []
    for slug in sorted(slugs):
        dirs = source_dirs(data_dir, slug)
        records = dirs.records / "images.jsonl"
        if not records.is_file():
            raise InventoryError(f"{slug}: no image records; run `openinspect ingest run {slug}`")
        for line in records.read_text(encoding="utf-8").splitlines():
            record = ImageRecord.model_validate_json(line)
            if not record.decode_ok:
                skipped.append(
                    Unreadable(
                        slug,
                        record.source_item_id,
                        record.sha256,
                        "ingest",
                        record.decode_error or "",
                    )
                )
                continue
            items.append(
                ImageItem(
                    source=slug,
                    item_id=record.source_item_id,
                    path=dirs.extracted / record.source_item_id,
                    sha256=record.sha256,
                    split=record.original_split,
                    group_id=record.source_group_id,
                    subgroup_id=record.source_subgroup_id,
                    n_annotations=record.n_annotations,
                    dhash=int(record.dhash, 16) if record.dhash else None,
                    width=record.width,
                    height=record.height,
                    acquisition_id=acquisition.get(slug),
                    flags=tuple(record.flags),
                )
            )
    items.sort(key=lambda item: item.key)
    return items, skipped
