from __future__ import annotations

import ast
import zipfile
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pytest
from numpy.typing import NDArray

import openinspect.exportcheck as exportcheck
from openinspect.exportcheck import validate_archive, validate_file
from openinspect.readiness.giant import (
    COHESIVE_MARGIN,
    ScanGraph,
    crop_graph,
    decompose,
    scan_graph,
    sweep,
    verdict,
)
from openinspect.readiness.labels import (
    Finding,
    LabelsError,
    place,
    read_findings,
    summarize,
)
from openinspect.readiness.probe import (
    describe_tree,
    fit_logistic,
    fit_tree,
    group_folds,
    predict_logistic,
    predict_tree,
    run_probe,
    stratified_folds,
)
from openinspect.release.groups import Constraint
from tests.readiness_helpers import candidate, png, yolo_zip

# ------------------------------------------------------------------------- exportcheck


GOOD = "0 0.5 0.5 0.2 0.2\n1 0.25 0.25 0.1 0.1\n"


def test_a_valid_package_passes_and_counts_everything() -> None:
    data = yolo_zip(
        {"train/a": GOOD, "val/b": "2 0.5 0.5 0.4 0.4\n", "test/c": "3 0.1 0.1 0.1 0.1\n"}
    )
    result = validate_archive(data)
    assert result.ok, result.examples
    assert result.images == {"test": 1, "train": 1, "val": 1}
    assert result.boxes == {"short": 1, "open": 1, "mouse_bite": 1, "spurious_copper": 1}
    assert result.rows == 4
    assert len(result.archive_sha256) == 64


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("0 0.5 0.5 0.2\n", "row_not_five_fields"),
        ("0 a 0.5 0.2 0.2\n", "row_not_numeric"),
        ("0 nan 0.5 0.2 0.2\n", "row_not_finite"),
        ("7 0.5 0.5 0.2 0.2\n", "class_id_invalid"),
        ("0.5 0.5 0.5 0.2 0.2\n", "class_id_invalid"),
        ("0 1.5 0.5 0.2 0.2\n", "coordinate_outside_unit_range"),
        ("0 0.5 0.5 0.0 0.2\n", "box_not_positive"),
        ("0 0.95 0.5 0.3 0.2\n", "box_outside_image"),
    ],
)
def test_every_kind_of_bad_row_is_caught(text: str, problem: str) -> None:
    labels = {"train/a": GOOD, "train/b": "2 0.5 0.5 0.1 0.1\n3 0.5 0.5 0.1 0.1\n", "train/x": text}
    result = validate_archive(yolo_zip(labels))
    assert not result.ok
    assert result.problems[problem] == 1


def test_a_box_leaving_the_image_by_less_than_half_a_pixel_passes_and_is_counted() -> None:
    labels = {
        "train/a": GOOD,
        # a DsPCBSD+ box of the release: four-decimal source labels, 0.0113 px past a 226 px edge
        "train/b": "2 0.5 0.5 0.1 0.1\n3 0.849600 0.303100 0.300900 0.606200\n",
        "val/c": "0 0.9025 0.5 0.205 0.2\n",  # 0.2 px past the right edge of a 40 px image
        "val/d": "0 0.9 0.5 0.2 0.2\n",  # on the edge: no overhang
    }
    images = {key: png() for key in labels} | {"train/b": png(226, 226)}
    result = validate_archive(yolo_zip(labels, images=images))
    assert result.ok, result.examples
    assert result.overhangs == 2
    assert result.max_overhang_px == pytest.approx(0.2)


def test_a_box_leaving_the_image_by_more_than_half_a_pixel_fails() -> None:
    labels = {
        "train/a": GOOD,
        "train/b": "2 0.5 0.5 0.1 0.1\n3 0.5 0.5 0.1 0.1\n",
        "val/c": "0 0.91 0.5 0.22 0.2\n",  # 0.8 px past the right edge
    }
    result = validate_archive(yolo_zip(labels))
    assert result.problems["box_outside_image"] == 1
    assert result.overhangs == 0


def test_missing_files_unreadable_images_and_unused_classes_are_caught() -> None:
    labels = {"train/a": "0 0.5 0.5 0.2 0.2\n", "train/orphan": "0 0.5 0.5 0.2 0.2\n"}
    images = {"train/a": png(), "train/nolabel": png(), "train/broken": b"not an image"}
    result = validate_archive(yolo_zip(labels, images=images))
    assert result.problems["label_without_image"] == 1
    assert result.problems["image_without_label"] == 1
    assert result.problems["image_unreadable"] == 1
    assert result.problems["class_never_used"] == 3
    assert result.examples


def test_a_broken_data_yaml_is_a_problem(tmp_path: Path) -> None:
    data = yolo_zip({"train/a": GOOD}, data_yaml="nc: 2\nnames: [a]\n")
    assert validate_archive(data).problems["data_yaml"] == 1
    path = tmp_path / "p.zip"
    path.write_bytes(yolo_zip({"train/a": GOOD}, data_yaml=": : :"))
    assert validate_file(path).problems["data_yaml"] == 1


def test_empty_label_files_are_counted_not_failed() -> None:
    result = validate_archive(
        yolo_zip(
            {"train/a": GOOD, "train/b": "", "val/c": "2 0.5 0.5 0.1 0.1\n3 0.5 0.5 0.1 0.1\n"}
        )
    )
    assert result.empty_label_files == 1
    assert result.ok


def test_the_independent_parser_imports_nothing_from_openinspect() -> None:
    tree = ast.parse(Path(exportcheck.__file__).read_text(encoding="utf-8"))
    modules = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)] + [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ]
    assert not [m for m in modules if m.startswith("openinspect")]
    assert zipfile.is_zipfile(__import__("io").BytesIO(yolo_zip({"train/a": GOOD})))


# ------------------------------------------------------------------------------ labels


def finding(signal: str, image: str, ann: int | None, *, related: str | None = None) -> Finding:
    return Finding(
        review_id=f"LQ-{signal}-{image}",
        check="geometry",
        signal=signal,
        source="s",
        image=image,
        ann_index=ann,
        related_source="s" if related else None,
        related_image=related,
        related_ann_index=None,
    )


def test_findings_are_placed_against_released_boxes_and_images() -> None:
    items = [
        candidate("OI_s_1", "s", ("short", "open"), item_id="a.jpg"),
        candidate("OI_s_2", "s", ("short",), item_id="b.jpg"),
        candidate("OI_s_3", "s", ("open",), item_id="c.jpg", crop=(0, 0, 10, 10)),
    ]
    findings = [
        finding("zero_area_box", "a.jpg", 1),  # released box: FATAL
        finding("tiny_box", "b.jpg", 0),  # released box: TRAINING_RELEVANT
        finding("class_size_outlier", "a.jpg", 0),  # LIMITATION_ONLY
        finding("class_size_outlier", "a.jpg", 9),  # that box is not released
        finding("near_duplicate_label_conflict", "a.jpg", None, related="b.jpg"),
        finding("near_duplicate_label_conflict", "a.jpg", None, related="zzz.jpg"),
        finding("near_duplicate_label_conflict", "y.jpg", None, related="zzz.jpg"),
        finding("mapping_ambiguity", "gone.jpg", 0),
    ]
    placed = place(findings, items)
    assert [p.category for p in placed] == [
        "FATAL",
        "TRAINING_RELEVANT",
        "LIMITATION_ONLY",
        "NOT_IN_RELEASE",
        "TRAINING_RELEVANT",
        "LIMITATION_ONLY",
        "NOT_IN_RELEASE",
        "NOT_IN_RELEASE",
    ]
    assert placed[0].released_items == ["OI_s_1"]
    assert placed[4].related_items == ["OI_s_2"]
    summary = summarize(
        placed,
        {
            "A": {"OI_s_1": "train", "OI_s_2": "test", "OI_s_3": "val"},
            "B": dict.fromkeys(["OI_s_1", "OI_s_2", "OI_s_3"], "train"),
        },
    )
    assert summary.by_category == {
        "FATAL": 1,
        "TRAINING_RELEVANT": 2,
        "LIMITATION_ONLY": 2,
        "NOT_IN_RELEASE": 3,
    }
    assert summary.fatal_items == ["OI_s_1"]
    assert summary.released_boxes_affected["FATAL"] == 1
    assert summary.pairs_across_splits == {"A": 1, "B": 0}


def test_an_unknown_signal_has_no_rule() -> None:
    with pytest.raises(LabelsError, match="no category rule"):
        place(
            [finding("brand_new_signal", "a.jpg", 0)], [candidate("OI_s_1", "s", item_id="a.jpg")]
        )


def test_the_queue_file_is_read(tmp_path: Path) -> None:
    path = tmp_path / "q.csv"
    path.write_text(
        "review_id,status,check,signal,source_id,image_id,ann_index,original_label,normalized_label,"
        "mapping_status,related_source_id,related_image_id,related_ann_index,related_labels,measure,"
        "detail,human_decision,human_notes\n"
        "LQ-1,REVIEW_REQUIRED,geometry,tiny_box,s,a.jpg,0,SH,short,EXACT,,,,,1.9,x,,\n",
        encoding="utf-8",
    )
    (f,) = read_findings(path)
    assert (f.signal, f.ann_index, f.related_image) == ("tiny_box", 0, None)
    with pytest.raises(LabelsError, match="cannot read"):
        read_findings(tmp_path / "missing.csv")


# ------------------------------------------------------------------------------- probe


def blobs(n: int = 60, seed: int = 0) -> tuple[NDArray[np.float64], NDArray[np.int64]]:
    rng = np.random.default_rng(seed)
    y = np.repeat(np.arange(3), n)
    x = rng.normal(size=(3 * n, 2)) + np.array([[0, 0], [6, 0], [0, 6]])[y]
    return x, y.astype(np.int64)


def test_both_models_separate_well_separated_classes() -> None:
    x, y = blobs()
    weights = fit_logistic(x, y, 3)
    assert (predict_logistic(weights, x) == y).mean() > 0.97
    tree = fit_tree(x, y, 3)
    assert (predict_tree(tree, x) == y).mean() > 0.97
    lines = describe_tree(tree, ["f0", "f1"], ["a", "b", "c"])
    assert any(line.startswith("if f") for line in lines)


def test_a_pure_node_is_a_leaf() -> None:
    x = np.zeros((20, 1))
    y = np.zeros(20, dtype=np.int64)
    assert fit_tree(x, y, 2).left is None


def test_folds_are_stratified_or_keep_groups_whole() -> None:
    labels = [0] * 10 + [1] * 10
    folds = stratified_folds([f"i{k}" for k in range(20)], labels, 5, 0)
    assert all(
        sorted(f for f, c in zip(folds, labels, strict=True) if c == cls)
        == [0, 0, 1, 1, 2, 2, 3, 3, 4, 4]
        for cls in (0, 1)
    )
    groups = [f"g{k // 4}" for k in range(20)]
    gfolds = group_folds(groups, labels, 5, 0)
    for g in set(groups):
        assert len({f for f, h in zip(gfolds, groups, strict=True) if h == g}) == 1


def test_the_probe_reports_scores_and_trees() -> None:
    x, y = blobs(30)
    names = ["src-a", "src-b", "src-c"]
    table = {
        f: [0.0] * len(y)
        for f in (
            "width",
            "height",
            "aspect",
            "log_pixels",
            "is_png",
            "n_boxes",
            "mean_rel_side",
            "min_rel_side",
            "max_rel_side",
            "mean_cx",
            "mean_cy",
            "std_cx",
            "std_cy",
            "mean_r",
            "mean_g",
            "mean_b",
            "std_r",
            "std_g",
            "std_b",
            "grad_mean",
        )
    }
    table["width"] = [float(v) for v in x[:, 0]]
    table["mean_r"] = [float(v) for v in x[:, 1]]
    result = run_probe(
        table,
        [names[c] for c in y],
        [f"id{k}" for k in range(len(y))],
        [f"g{k // 3}" for k in range(len(y))],
    )
    assert result.majority_baseline == pytest.approx(1 / 3)
    best = max(s.balanced_accuracy for s in result.scores)
    assert best > 0.9
    assert {s.folds for s in result.scores} == {"stratified", "group-aware"}
    assert "metadata" in result.trees
    assert "balanced accuracy" in result.reading


# ------------------------------------------------------------------------------- giant


def unit(v: Sequence[Sequence[float]]) -> NDArray[np.float32]:
    a = np.array(v, dtype=np.float32)
    return a / np.linalg.norm(a, axis=1, keepdims=True)


def chain() -> NDArray[np.float32]:
    """Six vectors on an arc: neighbours are similar, the ends are not."""
    angles = np.linspace(0, 1.5, 6)
    return unit([[float(np.cos(a)), float(np.sin(a)), 0.0] for a in angles])


def test_a_chain_has_a_gap_and_a_diameter() -> None:
    vectors = chain()
    graph = scan_graph(vectors, ["f1", "f1", "f2", "f2", "f3", "f3"], 0.9, "m")
    assert graph.largest == 6
    assert graph.largest_families == 3
    assert graph.diameter == 5
    assert graph.chaining_gap is not None
    assert graph.chaining_gap > 0.5
    assert graph.edge_min is not None
    assert graph.all_pairs_min is not None
    assert graph.edge_min >= 0.9 > graph.all_pairs_min


def test_no_edge_gives_an_empty_graph() -> None:
    graph = scan_graph(unit([[1, 0, 0], [0, 1, 0]]), [None, None], 0.99, "m")
    assert graph.components == 0
    assert graph.diameter is None


def test_the_sweep_grows_the_largest_component_as_the_threshold_drops() -> None:
    points = sweep(chain(), [0.99, 0.9], "m")
    assert points[0].largest_share < points[1].largest_share


def test_decomposition_joins_constraint_kinds_step_by_step() -> None:
    items = [candidate(f"OI_d_{k}", "d", crop=(0, 0, 5, 5)) for k in range(6)]
    found = [
        Constraint("crop_parent", "p1", (0, 1)),
        Constraint("crop_parent", "p2", (2, 3)),
        Constraint("metadata_group", "f1", (1, 2)),
        Constraint("similarity_component", "c1", (3, 4)),
    ]
    rows = {tuple(d.kinds): d for d in decompose(items, found, "d")}
    assert rows[("crop_parent",)].largest == 2
    assert rows[("crop_parent", "metadata_group")].largest == 4
    assert rows[("crop_parent", "similarity_component")].largest == 3
    assert (
        rows[("metadata_group", "similarity_component", "exact_duplicate", "crop_parent")].largest
        == 5
    )


def test_crop_level_components_with_constraints() -> None:
    items = [
        candidate(
            f"OI_d_{k}",
            "d",
            item_id=f"scan{k // 2}.jpg",
            group_id=f"fam{k // 4}",
            crop=(0, 0, 5, 5),
        )
        for k in range(8)
    ]
    vectors = unit([[1, 0, 0]] * 4 + [[0, 1, 0]] * 4)
    graph = crop_graph(items, vectors, 0.9, "m", [f"{k:064x}" for k in range(8)])
    assert graph.largest_component == 4
    assert graph.largest_group_with_constraints == 4
    assert graph.cross_scan_edges > 0
    assert graph.cross_family_edges == 0


def _graph(model: str, largest: int, all_min: float, gap: float, diameter: int) -> ScanGraph:
    return ScanGraph(
        model=model,
        threshold=0.9,
        scans=100,
        edges=200,
        components=5,
        largest=largest,
        largest_families=10,
        families=20,
        edge_min=0.9,
        all_pairs_min=all_min,
        all_pairs_mean=0.8,
        chaining_gap=gap,
        diameter=diameter,
        mean_path=2.0,
    )


def test_the_verdict_rules() -> None:
    cohesive = _graph("small", 60, 0.9 - COHESIVE_MARGIN, 0.0, 1)
    assert verdict(cohesive, _graph("base", 60, 0.9, 0, 1), None, 800)[0] == "A"
    chained = _graph("small", 60, 0.5, 0.4, 6)
    code, causes = verdict(chained, _graph("base", 60, 0.9, 0, 1), None, 800)
    assert code == "B"
    assert causes
    mixed, _ = verdict(chained, _graph("base", 10, 0.9, 0, 1), None, 800)
    assert mixed == "E"
    none, _ = verdict(
        _graph("small", 60, 0.5, 0.01, 1), _graph("base", 60, 0.5, 0.01, 1), None, 800
    )
    assert none == "undetermined"


def test_probe_results_agree_within_tolerance_but_trees_must_be_equal() -> None:
    from openinspect.readiness.check import probe_agrees

    x, y = blobs(20)
    names = ["a", "b", "c"]
    table = {
        f: [0.0] * len(y)
        for f in __import__("openinspect.readiness.probe", fromlist=["FEATURES"]).FEATURES
    }
    table["width"] = [float(v) for v in x[:, 0]]
    result = run_probe(
        table,
        [names[c] for c in y],
        [f"i{k}" for k in range(len(y))],
        [f"g{k}" for k in range(len(y))],
    )
    assert probe_agrees(result, result)
    nudged = result.model_copy(
        update={
            "scores": [s.model_copy(update={"accuracy": s.accuracy + 0.001}) for s in result.scores]
        }
    )
    assert probe_agrees(result, nudged)
    far = result.model_copy(
        update={
            "scores": [s.model_copy(update={"accuracy": s.accuracy + 0.1}) for s in result.scores]
        }
    )
    assert not probe_agrees(result, far)
    assert not probe_agrees(result, result.model_copy(update={"trees": {}}))
    assert not probe_agrees(result, result.model_copy(update={"scores": result.scores[:-1]}))
