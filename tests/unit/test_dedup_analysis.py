from __future__ import annotations

import numpy as np
import pytest

from openinspect.dedup.analysis import (
    CONTROL,
    AnalysisError,
    AnalysisResult,
    Neighbours,
    allocate,
    candidate_pairs,
    category_counts,
    cdf,
    control_pairs,
    cross_source_summary,
    crossing,
    filter_edges,
    hash_baseline,
    key_agreement,
    make_views,
    review_queue,
    run_analysis,
    source_graphs,
    sweep_grid,
    sweep_labels,
    synthetic_recall,
    synthetic_summary,
)
from openinspect.dedup.audit_models import Audit, LevelResult
from openinspect.dedup.calibrate import NBINS, bin_of, curve_from_histograms
from openinspect.dedup.compute import FeatureSet
from openinspect.dedup.graph import GraphError, collect_edges, components
from openinspect.dedup.inventory import Unreadable
from openinspect.dedup.leakage import SourceLeakage
from openinspect.dedup.synthetic import SyntheticPair
from openinspect.dedup.thresholds import CATEGORIES, PoolCurve, select_thresholds
from tests.dedup_helpers import Clustered, clustered_features, make_spec, repository_settings

SPEC = make_spec(dim=16)


@pytest.fixture(scope="module")
def clustered() -> Clustered:
    return clustered_features()


@pytest.fixture(scope="module")
def result(clustered: Clustered) -> AnalysisResult:
    skipped = [Unreadable("pcb-ind", "YOLO/broken.jpg", "f" * 64, "ingest", "truncated")]
    return run_analysis(
        clustered.features,
        clustered.synthetic,
        spec=SPEC,
        weights_sha256="0" * 64,
        skipped=skipped,
        settings=repository_settings(permutations=200, resamples=200),
    )


def leak(result: AnalysisResult, level: str, source: str) -> tuple[LevelResult, SourceLeakage]:
    lv = next(x for x in result.audit.levels if x.level == level)
    return lv, next(x for x in lv.leakage if x.source == source)


def test_the_rule_is_applied_and_the_fallback_is_recorded(result: AnalysisResult) -> None:
    t = result.audit.thresholds
    assert t.review <= t.family <= t.near
    ind = next(p for p in t.from_pools if p.source == "pcb-ind")
    assert ind.precision_090 is not None  # tight (batch, side) clusters reach precision 0.90
    assert ind.fallback is None
    defect = [p for p in t.from_pools if p.source == "pcb-defect"]
    assert {p.pool for p in defect} == {"family A", "(A, B)"}
    assert all(p.precision_090 is None and "F1" in (p.fallback or "") for p in defect)
    assert t.family == max(p.family for p in t.from_pools if p.used_in_rule and p.family)
    assert t.near >= t.family
    assert t.phash_candidate == 3  # 95% of the photometric copies are within three bits


def test_cross_split_groups_are_found_where_they_were_planted(result: AnalysisResult) -> None:
    _, dsp = leak(result, "near", "dspcbsd-plus")
    assert dsp.groups_crossing_any == 4  # clusters 0 to 3 have a validation member
    assert dsp.crossing.train_val == 4
    assert dsp.affected_images == 12
    _, ind = leak(result, "near", "pcb-ind")
    assert ind.groups_crossing_any >= 1  # the cross-batch twin (train | test)
    assert ind.crossing.train_test >= 1
    _, defect = leak(result, "near", "pcb-defect")
    assert defect.has_splits is False
    assert defect.groups_crossing_any == 0


def test_the_key_cannot_see_the_cross_batch_twin(result: AnalysisResult) -> None:
    level = next(x for x in result.audit.levels if x.level == "near")
    overlap = next(o for o in level.key_overlap if o.source == "pcb-ind")
    assert overlap.edge_mix.cross_split_other_group >= 1
    assert overlap.edge_mix.cross_split_same_subgroup == 0
    assert overlap.only_similarity is not None
    assert overlap.only_similarity >= 2
    assert {o.source for o in level.key_overlap} == {"pcb-ind", "pcb-defect"}


def test_baselines_and_reconstructed_splits(result: AnalysisResult) -> None:
    for level in result.audit.levels:
        assert level.permutation["pcb-defect"] is None  # no split to shuffle
        assert level.reconstructed["pcb-defect"] is None
        for source in ("dspcbsd-plus", "pcb-ind"):
            baseline = level.permutation[source]
            assert baseline is not None
            assert baseline.n_permutations == 200
            rebuilt = level.reconstructed[source]
            assert rebuilt is not None
            assert rebuilt.groups_crossing == 0  # measured, not assumed


def test_categories_hashes_and_exact_duplicates(
    result: AnalysisResult, clustered: Clustered
) -> None:
    audit = result.audit
    count = {(c.scope, c.category): c.pairs for c in audit.categories}
    assert count[("within:dspcbsd-plus", "EXACT_DUPLICATE")] == 1
    assert audit.hash_audit.sha256_equal_pairs == 1
    assert audit.hash_audit.sha256_equal_groups == 1
    assert audit.cross_source.sha256_equal_pairs == 0
    scopes = {s.scope for s in audit.hash_audit.scopes}
    assert "across:dspcbsd-plus|pcb-ind" in scopes
    assert set(audit.hash_audit.phash_in_family_group) == {"dspcbsd-plus", "pcb-defect", "pcb-ind"}
    # the planted pair whose hashes agree while the embeddings do not is a review case
    items = [f"{i.source}:{i.item_id}" for i in clustered.features.items]
    a, b = items.index("dspcbsd-plus:S_x07.jpg"), items.index("dspcbsd-plus:S_x08.jpg")
    hit = (result.pairs.i == min(a, b)) & (result.pairs.j == max(a, b))
    assert hit.sum() == 1
    assert CATEGORIES[int(result.pairs.category[hit][0])] == "REVIEW_REQUIRED"


def test_run_info_top1_transfer_and_stability(result: AnalysisResult, clustered: Clustered) -> None:
    run = result.audit.run
    assert run.images == len(clustered.features.items) + 1  # plus the image skipped at ingest
    assert run.skipped_at_ingest == 1
    ind = next(s for s in run.sources if s.source == "pcb-ind")
    assert ind.failed == 1
    assert ind.group_key == "batch"
    assert ind.splits == {"train": 35, "val": 15, "test": 10}
    assert next(s for s in run.sources if s.source == "dspcbsd-plus").group_key is None
    top = {s.source: s for s in result.audit.top1}
    assert top["pcb-ind"].top1_same_subgroup is not None
    assert top["pcb-ind"].chance_same_subgroup is not None
    assert top["pcb-ind"].top1_same_subgroup > top["pcb-ind"].chance_same_subgroup
    assert top["dspcbsd-plus"].top1_same_group is None
    assert top["pcb-ind"].cdf[-1] == (1.0, 1.0)
    assert {r.source: r.labelled for r in result.audit.transfer} == {
        "dspcbsd-plus": False,
        "pcb-defect": True,
        "pcb-ind": True,
    }
    assert result.audit.stability
    assert all(
        r.retained_pairs is None or 0 <= r.retained_pairs <= 1 for r in result.audit.stability
    )
    assert result.audit.synthetic is not None
    assert result.audit.synthetic.sample_per_source == 5


def test_groups_table_and_ids(result: AnalysisResult, clustered: Clustered) -> None:
    levels = {row.level for row in result.group_rows}
    assert levels == {"near", "family"}
    assert all(row.group_id.startswith(f"VSG-{row.level}-") for row in result.group_rows)
    assert any(row.cross_split for row in result.group_rows)
    ids = result.group_ids
    assert len(ids["near"]) == len(clustered.features.items)
    assert sum(1 for x in ids["near"] if x is not None) == sum(
        len(r.members) for r in result.group_rows if r.level == "near"
    )


def test_the_review_queue_is_seeded_stratified_and_bounded(
    result: AnalysisResult, clustered: Clustered
) -> None:
    queue = result.review
    assert len(queue) == 300
    assert len({r.pair_id for r in queue}) == 300
    assert len({(r.i, r.j) for r in queue}) == 300
    assert any(r.machine_category == CONTROL for r in queue)
    strata = {r.stratum for r in queue}
    # the four axes: scope, the rule's band, the split relation and the metadata relation
    assert all(len(s.split("|")) == 4 for s in strata)
    assert any(s.endswith("|cross-split|other-group") for s in strata)
    assert any(s.endswith("|same-group") for s in strata)
    assert any("|no-split|" in s for s in strata)
    assert any(s.startswith("across|") for s in strata)
    again = review_queue(
        clustered.features,
        result.pairs,
        result.neighbours,
        result.audit.thresholds,
        budget=300,
        seed=0,
    )
    assert again == queue
    other = review_queue(
        clustered.features,
        result.pairs,
        result.neighbours,
        result.audit.thresholds,
        budget=300,
        seed=1,
    )
    assert other != queue
    small = review_queue(
        clustered.features,
        result.pairs,
        result.neighbours,
        result.audit.thresholds,
        budget=10,
        seed=0,
    )
    assert len(small) == 10


def test_the_audit_survives_a_json_round_trip(result: AnalysisResult) -> None:
    text = result.audit.model_dump_json()
    assert Audit.model_validate_json(text) == result.audit


def test_the_same_inputs_give_the_same_audit(clustered: Clustered, result: AnalysisResult) -> None:
    again = run_analysis(
        clustered.features,
        clustered.synthetic,
        spec=SPEC,
        weights_sha256="0" * 64,
        skipped=[Unreadable("pcb-ind", "YOLO/broken.jpg", "f" * 64, "ingest", "truncated")],
        settings=repository_settings(permutations=200, resamples=200),
    )
    assert again.audit == result.audit


def test_too_few_images_is_an_error(clustered: Clustered) -> None:
    one = FeatureSet(
        clustered.features.items[:1],
        clustered.features.vectors[:1],
        clustered.features.phash[:1],
        clustered.features.dhash[:1],
    )
    with pytest.raises(AnalysisError):
        run_analysis(one, [], spec=SPEC, weights_sha256="0" * 64)


def test_sweep_labels_match_components_at_every_threshold(clustered: Clustered) -> None:
    vectors = make_views(clustered.features)[2].vectors  # pcb-ind
    edges = collect_edges(vectors, 0.5)
    thresholds = [0.95, 0.9, 0.8, 0.6, 0.5]
    for threshold, count, labels in sweep_labels(len(vectors), edges, thresholds):
        kept = filter_edges(edges, threshold)
        assert count == len(kept[0])
        assert labels.tolist() == components(len(vectors), [(kept[0], kept[1])]).tolist()


def test_crossing_counts_groups_in_two_or_more_known_splits() -> None:
    labels = np.array([0, 0, 2, 2, 4, 4, 6], dtype=np.int64)
    splits = np.array([0, 1, 0, 0, 1, -1, 2], dtype=np.int8)
    assert crossing(labels, splits) == (1, 2)
    assert crossing(np.empty(0, dtype=np.int64), np.empty(0, dtype=np.int8)) == (0, 0)


def test_allocate_shares_the_budget_and_passes_on_what_is_unused() -> None:
    assert allocate({"a": 100, "b": 100, "c": 100}, 30) == {"a": 10, "b": 10, "c": 10}
    assert allocate({"a": 2, "b": 100}, 30) == {"a": 2, "b": 28}
    assert allocate({"a": 3, "b": 4}, 30) == {"a": 3, "b": 4}
    assert allocate({}, 30) == {}
    assert sum(allocate({"a": 7, "b": 7, "c": 7}, 10).values()) == 10


def test_key_agreement_and_cdf() -> None:
    top1 = np.array([1, 0, 3, 2], dtype=np.int64)
    assert key_agreement(["x", "x", "y", "z"], top1) == (0.5, round(2 / 12, 6))
    assert key_agreement([None, None, "a", None], top1) == (None, None)
    assert key_agreement(["a", "a"], np.array([1], dtype=np.int64)) == (None, None)
    assert cdf(np.empty(0, dtype=np.float32)) == []
    points = cdf(np.array([0.2, 0.5, 0.5, 0.9], dtype=np.float32))
    assert points[0] == (0.0, 0.0)
    assert points[50] == (0.5, 0.75)
    assert points[-1] == (1.0, 1.0)
    shares = [s for _, s in points]
    assert shares == sorted(shares)


def test_hash_baseline_reads_small_distances_as_similar() -> None:
    positive = np.zeros(65, dtype=np.int64)
    negative = np.zeros(65, dtype=np.int64)
    positive[1] = 60
    negative[30] = 600
    baseline = hash_baseline("phash", positive, negative)
    assert baseline.auc == 1.0
    assert baseline.best_distance is not None
    assert 1 <= baseline.best_distance < 30
    assert baseline.best_f1 == 1.0
    empty = hash_baseline("dhash", np.zeros(65, dtype=np.int64), negative)
    assert empty.best_distance is None
    assert empty.auc is None


def test_sweep_grid_holds_the_rule_values(result: AnalysisResult) -> None:
    t = result.audit.thresholds
    grid = sweep_grid(t, 0.02)
    assert {t.review, t.family, t.near} <= set(grid)
    assert grid == sorted(grid)
    assert max(grid) <= 1.0


def test_source_graphs_raise_the_floor_or_refuse(clustered: Clustered) -> None:
    view = make_views(clustered.features)[0]  # dspcbsd-plus
    grid = [0.0, 0.5, 0.9, 0.97]
    graphs = source_graphs(view, grid, max_edges=40, protected=0.97)
    assert graphs.floor > 0.0
    assert graphs.note is not None
    assert "sweep starts at" in graphs.note
    assert set(graphs.labels) == {t for t in grid if t >= graphs.floor}
    with pytest.raises(GraphError):
        source_graphs(view, grid, max_edges=0, protected=0.0)


def test_candidate_pairs_join_cosine_hash_and_bytes(
    clustered: Clustered, result: AnalysisResult
) -> None:
    pairs = candidate_pairs(clustered.features, result.audit.thresholds, 10_000)
    assert len(pairs.i) == len(result.pairs.i)
    assert (pairs.i < pairs.j).all()
    assert (pairs.category >= 0).all()
    assert int(pairs.sha_equal.sum()) == 1
    counts = category_counts(clustered.features, pairs)
    assert sum(c.pairs for c in counts) == len(pairs.i)
    assert all(c.cross_source == 0 for c in counts if c.scope != "across")
    assert all(c.cross_source == c.pairs for c in counts if c.scope == "across")


def test_cross_source_summary_orders_the_top_pairs(
    clustered: Clustered, result: AnalysisResult
) -> None:
    summary = cross_source_summary(
        make_views(clustered.features), result.audit.thresholds, 0, top=5
    )
    assert len(summary.top_pairs) == 5
    cosines = [s for _, _, s in summary.top_pairs]
    assert cosines == sorted(cosines, reverse=True)
    levels = {(e.level, e.source_a, e.source_b) for e in summary.edges}
    assert len(levels) == 9  # three levels x three source pairs
    for edge in summary.edges:
        assert (edge.pairs == 0) == (edge.images_a == 0) == (edge.images_b == 0)


def test_synthetic_summary_and_control_pairs(clustered: Clustered, result: AnalysisResult) -> None:
    assert synthetic_summary([], result.audit.thresholds, 0) is None
    summary = synthetic_summary(clustered.synthetic, result.audit.thresholds, 0)
    assert summary is not None
    assert [r.transform for r in summary.by_transform] == [
        "jpeg_q75",
        "brightness_up",
        "blur",
        "crop_90",
        "crop_80",
    ]
    assert {r.kind for r in summary.by_source} == {"dspcbsd-plus", "pcb-defect", "pcb-ind"}
    empty = Neighbours(np.empty((3, 0), dtype=np.int64), np.empty((3, 0), dtype=np.float32), {}, {})
    control = control_pairs(clustered.features, result.pairs, empty, 0.5)
    assert len(control.i) == 0
    real = control_pairs(
        clustered.features, result.pairs, result.neighbours, result.audit.thresholds.review
    )
    assert (real.cosine < result.audit.thresholds.review).all()
    assert (real.category == -1).all()


def test_a_family_threshold_above_the_synthetic_one_lowers_the_achieved_recall() -> None:
    # the labelled pool puts family near 0.85; the synthetic copies of "s" spread from 0.70 to 0.99
    pos = np.zeros(NBINS, dtype=np.int64)
    neg = np.zeros(NBINS, dtype=np.int64)
    pos[bin_of(0.95)] = 100
    neg[bin_of(0.85)] = 1000
    curve = PoolCurve("pool-source", "g", True, curve_from_histograms(pos, neg))
    cosines = np.linspace(0.70, 0.99, 100)
    synthetic = [
        SyntheticPair("s", f"{k}.png", f"{k:064x}", "blur", "photometric", True, float(c), 1, 1)
        for k, c in enumerate(cosines)
    ]
    thresholds = select_thresholds([curve], synthetic, model="stub")
    (source,) = thresholds.from_synthetic
    assert source.near < thresholds.family  # the copies alone would allow a lower threshold
    assert thresholds.near == thresholds.family  # the rule takes the larger value
    (row,) = synthetic_recall(synthetic, thresholds)
    assert row.target_recall == 0.95
    assert row.source_threshold == source.near
    assert row.final_near_threshold == thresholds.near
    assert row.n_pairs == 100
    assert row.achieved_recall == pytest.approx(float((cosines >= thresholds.near).mean()))
    assert row.achieved_recall < 0.95
    assert row.meets_target is False


def test_the_achieved_recall_is_reported_where_the_target_holds(result: AnalysisResult) -> None:
    rows = {row.source: row for row in result.audit.synthetic_recall}
    assert set(rows) == {"dspcbsd-plus", "pcb-defect", "pcb-ind"}
    t = result.audit.thresholds
    assert all(row.final_near_threshold == t.near for row in rows.values())
    assert all(row.meets_target and row.achieved_recall >= 0.95 for row in rows.values())
    lowest = min(rows.values(), key=lambda row: row.source_threshold)
    assert lowest.source_threshold == pytest.approx(t.near)  # near came from this source


def test_components_report_their_chaining(result: AnalysisResult) -> None:
    for level in result.audit.levels:
        for cohesion in level.cohesion:
            assert cohesion.chaining_gap is not None
            assert cohesion.chaining_gap.minimum >= -1e-6  # the weakest edge is a member pair
            sizes = [c.size for c in cohesion.largest]
            assert sizes == sorted(sizes, reverse=True)
            assert len(cohesion.largest) == min(5, cohesion.groups)
            for component in cohesion.largest:
                assert component.chaining_gap == pytest.approx(
                    component.edge_min_similarity - component.all_pairs_min_similarity, abs=2e-6
                )
                assert component.edge_min_similarity >= level.threshold - 1e-6


def test_every_pool_has_both_uncertainty_intervals(result: AnalysisResult) -> None:
    for pool in result.audit.pools:
        assert [u.metric for u in pool.uncertainty] == [
            "ROC AUC",
            "average precision",
            "precision at family",
            "recall at family",
        ]
        assert pool.negative_units is not None
        assert pool.negative_units >= 2
        auc_check = pool.uncertainty[0]
        assert auc_check.primary is not None
        assert auc_check.both_sides is not None
        if auc_check.primary.high > auc_check.primary.low:
            assert auc_check.width_ratio is not None
            assert auc_check.width_ratio > 0
        else:  # a zero-width interval has no ratio
            assert auc_check.width_ratio is None
