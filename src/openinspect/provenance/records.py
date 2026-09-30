"""Image and annotation records produced by ingestion (SPEC §6.2 and §6.3).

At ingest time a record is keyed by (``source_dataset``, ``source_item_id``). The global
``OI_%06d`` id is assigned when a release is assembled (docs/DECISIONS.md, T8), not here.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from openinspect.provenance.schema import Sha256, Slug, Spdx, StrictModel, Url

Split = Literal["train", "val", "test"]


class ImageRecord(StrictModel):
    """One image of one source, with its provenance and the facts ingestion could check."""

    source_dataset: Slug
    source_item_id: str = Field(min_length=1)  # POSIX path inside the extracted archive
    source_url: Url
    source_license: Spdx
    sha256: Sha256  # of the file as shipped
    sha256_source: Sha256  # of the original upstream file (equal to ``sha256`` at ingest)
    bytes: int = Field(ge=0)
    decode_ok: bool
    decode_error: str | None = None
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    format: str | None = None
    mode: str | None = None
    exif_orientation: int | None = None
    dhash: str | None = Field(default=None, pattern=r"^[0-9a-f]{16}$")
    original_split: Split | None = None
    source_group_id: str | None = None  # best identifiable board / batch / design key, if any
    source_subgroup_id: str | None = None
    name_family: str | None = None  # shape of the file name (S_########, Y_######, ...)
    original_name: str | None = None  # a name the source itself records for the image
    original_labels: list[str] = Field(default_factory=list)
    n_annotations: int = Field(ge=0)
    annotation_source: str  # which format the boxes were read from
    alternate_paths: list[str] = Field(default_factory=list)  # other copies with the same bytes
    review_status: Literal["unreviewed"] = "unreviewed"
    flags: list[str] = Field(default_factory=list)


class AnnotationRecord(StrictModel):
    """One bounding box, in pixels of the image it belongs to."""

    source_dataset: Slug
    source_item_id: str = Field(min_length=1)
    ann_index: int = Field(ge=0)
    original_label: str = Field(min_length=1)  # exactly as the source names the class
    label_id: int | None = None
    bbox_xyxy: Annotated[list[float], Field(min_length=4, max_length=4)]
    in_bounds: bool
    flags: list[str] = Field(default_factory=list)
