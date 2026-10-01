"""Applying the taxonomy: original labels untouched, image eligibility by SPEC 7.4."""

from __future__ import annotations

from pathlib import Path

import pytest

from openinspect.dedup.inventory import InventoryError
from openinspect.taxonomy.config import Taxonomy, TaxonomyError
from openinspect.taxonomy.mapping import AnnotatedImage, load_annotated, map_images, used_labels
from tests.dedup_helpers import Spec, make_image, write_items, write_records
from tests.taxonomy_helpers import box, item, mapped, taxonomy, taxonomy_data, write_annotations


def test_original_labels_are_kept_next_to_the_normalized_ones() -> None:
    boxes = [box(0, "SH", (1, 1, 10, 10)), box(1, "OP", (20, 20, 30, 30))]
    image = mapped("src-a", "a.png", boxes)
    assert [m.box for m in image.boxes] == boxes  # the very same boxes, labels unchanged
    assert [(m.box.original_label, m.normalized_label, m.status) for m in image.boxes] == [
        ("SH", "short", "EXACT"),
        ("OP", "open", "COMPATIBLE"),
    ]
    assert image.eligibility == "eligible"
    assert image.excluded_by == ()


def test_an_image_with_any_non_benchmark_box_is_excluded_whole() -> None:
    image = mapped("src-a", "a.png", [box(0, "SH", (1, 1, 9, 9)), box(1, "SP", (2, 2, 8, 8))])
    assert image.eligibility == "excluded"
    assert image.excluded_by == ("SP",)
    assert [m.benchmark for m in image.boxes] == [True, False]


def test_ambiguous_and_source_specific_labels_never_count_as_benchmark() -> None:
    burr = mapped("src-b", "b.png", [box(0, "burr", (1, 1, 5, 5))])
    assert burr.boxes[0].normalized_label == "burr"  # kept as its own class, not merged
    assert not burr.boxes[0].benchmark
    hole = mapped("src-a", "h.png", [box(0, "HB", (1, 1, 5, 5))])
    assert hole.eligibility == "excluded"


def test_an_image_without_boxes_is_a_negative() -> None:
    assert mapped("src-b", "n.png", []).eligibility == "negative"


def test_mapping_needs_a_benchmark_class() -> None:
    data = taxonomy_data()
    data["mappings"]["src-b"]["short"] = {
        "normalized_label": "short",
        "status": "AMBIGUOUS",
        "candidate": "open",
        "evidence": "unclear whether it is a short",
    }
    data["mappings"]["src-b"]["open"]["status"] = "SOURCE_SPECIFIC"
    with pytest.raises(TaxonomyError, match="no benchmark class"):
        map_images([], Taxonomy.model_validate(data))


def test_an_unmapped_label_stops_the_mapping() -> None:
    image = AnnotatedImage(item("src-a", "x.png"), (box(0, "XX", (0, 0, 2, 2)),))
    with pytest.raises(TaxonomyError, match="has no mapping"):
        map_images([image], taxonomy())


def test_load_annotated_reads_the_records(tmp_path: Path) -> None:
    data = tmp_path / "data"
    specs = [Spec("a.png", make_image(1), "train"), Spec("b.png", make_image(2), "val")]
    write_records(data, "src-a", write_items(data, "src-a", specs))
    write_annotations(
        data, "src-a", [("a.png", 1, "OP", [5, 5, 9, 9]), ("a.png", 0, "SH", [1, 1, 4, 4])]
    )
    images = load_annotated(data, ["src-a"], acquisition={"src-a": "camera"})
    assert [(i.item.item_id, [b.original_label for b in i.boxes]) for i in images] == [
        ("a.png", ["SH", "OP"]),  # ordered by box index
        ("b.png", []),
    ]
    assert images[0].item.acquisition_id == "camera"
    assert used_labels(images) == {"src-a": ["OP", "SH"]}
    images_b = map_images(images, taxonomy())
    assert [i.eligibility for i in images_b] == ["eligible", "negative"]


def test_load_annotated_refuses_missing_records_and_orphan_boxes(tmp_path: Path) -> None:
    data = tmp_path / "data"
    write_records(data, "src-a", write_items(data, "src-a", [Spec("a.png", make_image(1))]))
    with pytest.raises(InventoryError, match="no annotation records"):
        load_annotated(data, ["src-a"])
    write_annotations(data, "src-a", [("ghost.png", 0, "SH", [1, 1, 3, 3])])
    with pytest.raises(InventoryError, match="no decodable image record"):
        load_annotated(data, ["src-a"])
