from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import pytest
from defusedxml import ElementTree

from openinspect.dedup.analysis import AnalysisResult, PairTable, run_analysis
from openinspect.dedup.audit_models import Audit
from openinspect.dedup.leakage import PermutationBaseline
from openinspect.dedup.perf import StageTiming, build_performance
from openinspect.dedup.report import (
    DASH,
    REPORTS,
    _reading,
    primary_level,
    render_reports,
    slug,
    write_reports,
)
from openinspect.dedup.tables import (
    AUDIT,
    GROUPS,
    NEIGHBOURS,
    PAIRS,
    REVIEW,
    REVIEW_COLUMNS,
    SYNTHETIC_RECALL,
    THRESHOLDS,
    pairs_table,
    read_audit,
    read_review,
    write_artifacts,
    write_audit,
)
from openinspect.dedup.thresholds import CATEGORIES, Thresholds
from tests.dedup_helpers import Clustered, clustered_features, make_spec, repository_settings


@pytest.fixture(scope="module")
def clustered() -> Clustered:
    return clustered_features()


@pytest.fixture(scope="module")
def result(clustered: Clustered) -> AnalysisResult:
    return run_analysis(
        clustered.features,
        clustered.synthetic,
        spec=make_spec(dim=16),
        weights_sha256="0" * 64,
        settings=repository_settings(permutations=100, resamples=100),
    )


def full_audit(result: AnalysisResult) -> Audit:
    performance = build_performance(
        [StageTiming("calibration", 1.5, 2_000_000), StageTiming("artifacts", 0.2, None)],
        features_runs=[
            {
                "embedded": 100,
                "wall_seconds": 10.0,
                "images_per_second": 10.0,
                "model_images_per_second": 11.0,
                "peak_ram_bytes": 3_000_000,
                "note": "transcribed",
            }
        ],
        synthetic_runs=[{"embedded": 50, "wall_seconds": 5.0, "peak_ram_bytes": 1_000_000}],
        cache_files=100,
        cache_bytes=160_000,
        dim=16,
    )
    return result.audit.model_copy(
        update={
            "run": result.audit.run.model_copy(
                update={"code_commit": "a" * 40, "code_dirty": True}
            ),
            "performance": performance,
            "artifacts": {PAIRS: "b" * 64},
        }
    )


# ------------------------------------------------------------------------ artifacts


def test_artifacts_are_readable_complete_and_deterministic(
    tmp_path: Path, clustered: Clustered, result: AnalysisResult
) -> None:
    first = write_artifacts(tmp_path / "a", clustered.features, result)
    second = write_artifacts(tmp_path / "b", clustered.features, result)
    assert first == second  # same inputs, same bytes
    assert set(first) == {PAIRS, NEIGHBOURS, GROUPS, REVIEW, THRESHOLDS, SYNTHETIC_RECALL}
    thresholds = Thresholds.model_validate_json((tmp_path / "a" / THRESHOLDS).read_text("utf-8"))
    assert thresholds == result.audit.thresholds
    recall = json.loads((tmp_path / "a" / SYNTHETIC_RECALL).read_text("utf-8"))
    assert [row["source"] for row in recall] == ["dspcbsd-plus", "pcb-defect", "pcb-ind"]
    assert all(row["final_near_threshold"] == thresholds.near for row in recall)
    pairs = pq.read_table(tmp_path / "a" / PAIRS).to_pylist()
    assert len(pairs) == len(result.pairs.i)
    assert {row["decision"] for row in pairs} == {"review"}
    assert {row["category"] for row in pairs} <= set(CATEGORIES)
    exact = [row for row in pairs if row["sha256_equal"]]
    assert len(exact) == 1
    assert exact[0]["category"] == "EXACT_DUPLICATE"
    assert all(row["cross_split"] is False for row in pairs if row["cross_source"])
    assert all(row["source_a"] and row["image_b"] for row in pairs)
    neighbours = pq.read_table(tmp_path / "a" / NEIGHBOURS)
    n, k = result.neighbours.index.shape
    assert neighbours.num_rows == n * k
    assert sorted(set(neighbours.column("rank").to_pylist())) == list(range(1, k + 1))
    groups = pq.read_table(tmp_path / "a" / GROUPS).to_pylist()
    assert len(groups) == len(result.group_rows)
    assert all(row["size"] == len(row["members"]) >= 2 for row in groups)
    review = read_review(tmp_path / "a" / REVIEW)
    assert len(review) == len(result.review)
    assert tuple(review[0]) == REVIEW_COLUMNS
    assert {row["human_decision"] for row in review} == {""}
    assert {row["human_notes"] for row in review} == {""}
    assert (tmp_path / "a" / REVIEW).read_bytes().count(b"\r") == 0


def test_the_audit_json_round_trips(tmp_path: Path, result: AnalysisResult) -> None:
    audit = full_audit(result)
    write_audit(tmp_path / AUDIT, audit)
    assert read_audit(tmp_path / AUDIT) == audit
    assert (tmp_path / AUDIT).read_bytes().endswith(b"}\n")


def test_an_empty_pair_table_still_has_every_column(
    clustered: Clustered, result: AnalysisResult
) -> None:
    empty = PairTable(
        np.empty(0, np.int64),
        np.empty(0, np.int64),
        np.empty(0, np.float32),
        np.empty(0, np.uint8),
        np.empty(0, np.uint8),
        np.empty(0, bool),
        np.empty(0, np.int8),
    )
    table = pairs_table(clustered.features, empty, result.group_ids)
    assert table.num_rows == 0
    assert "group_family" in table.column_names


def test_a_review_file_with_other_columns_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "review.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unexpected columns"):
        read_review(path)


# -------------------------------------------------------------------------- reports


def test_every_report_and_figure_is_rendered_and_linked(result: AnalysisResult) -> None:
    files = render_reports(full_audit(result))
    assert set(REPORTS) <= set(files)
    figures = {name for name in files if name.startswith("figures/")}
    assert {"figures/roc.svg", "figures/pr.svg", "figures/cross-split.svg"} <= figures
    for name in figures:
        ElementTree.fromstring(files[name])  # well-formed SVG
    linked = {
        f"figures/{m}" for name in REPORTS for m in re.findall(r"\(figures/([^)]+)\)", files[name])
    }
    assert linked == figures
    for name in REPORTS:
        text = files[name]
        assert "not proof that two images show the same physical object" in text
        assert "`aaaaaaaaaaaa` with uncommitted changes" in text
        assert "near-duplicate group" not in text  # a component is a potential leakage group


def test_the_reports_state_the_numbers_of_the_audit(result: AnalysisResult) -> None:
    audit = full_audit(result)
    files = render_reports(audit)
    t = audit.thresholds
    summary = files["similarity-summary.md"]
    assert f"{t.near:.4f}" in summary
    assert f"<= {t.phash_candidate} bits" in summary
    leakage = files["split-leakage.md"]
    family = next(level for level in audit.levels if level.level == "family")
    dsp = next(x for x in family.leakage if x.source == "dspcbsd-plus")
    assert f"{dsp.affected_images:,} of {dsp.n_images:,}" in leakage
    calibration = files["threshold-calibration.md"]
    assert "never reached" in calibration  # pcb-defect misses precision 0.90
    assert "## Synthetic positives" in calibration
    comparison = files["source-comparison.md"]
    assert "`pcb-ind`: its own keys (batch; (batch, side)) against DINOv2 components" in comparison
    assert "`dspcbsd-plus`: is there a latent grouping?" in comparison
    assert "second representation: not run" in comparison
    assert "## Largest visual similarity components" in comparison
    assert "## Synthetic recall at the final near threshold" in calibration
    assert "## Uncertainty: the protocol's bootstrap and a both-sides check" in calibration
    assert "## The sources' own keys across the splits" in leakage
    assert "Not run" in files["representation-robustness.md"]
    assert "No scalar score is given" in files["dataset-assurance.md"]
    assert "Leakage is not a score" in files["limitations.md"]
    performance = files["performance.md"]
    assert "embeddings (cache build)" in performance
    assert "b" * 64 in performance


def test_reports_render_without_the_optional_parts(result: AnalysisResult) -> None:
    bare = result.audit.model_copy(update={"synthetic": None, "performance": None, "pools": []})
    files = render_reports(bare)
    assert "Not computed." in files["threshold-calibration.md"]
    assert "No performance record." in files["performance.md"]
    assert "figures/roc.svg" not in files
    assert DASH in files["similarity-summary.md"]  # the commit is unknown


def test_write_reports_is_idempotent_and_drops_stale_figures(
    tmp_path: Path, result: AnalysisResult
) -> None:
    audit = full_audit(result)
    stale = tmp_path / "figures" / "old-figure.svg"
    stale.parent.mkdir(parents=True)
    stale.write_text("<svg/>", encoding="utf-8")
    first = {p.name: p.read_bytes() for p in write_reports(tmp_path, audit)}
    second = {p.name: p.read_bytes() for p in write_reports(tmp_path, audit)}
    assert first == second
    assert not stale.exists()
    assert all(b"\r\n" not in data for data in first.values())


def test_the_chaining_rule_picks_the_primary_level(result: AnalysisResult) -> None:
    audit = result.audit
    levels = [
        level.model_copy(update={"chained_sources": ["pcb-ind"]})
        if level.level == "family"
        else level
        for level in audit.levels
    ]
    chained = audit.model_copy(update={"levels": levels})
    assert primary_level(chained, "pcb-ind") == "near"
    assert primary_level(chained, "dspcbsd-plus") == "family"
    assert "Flagged: `pcb-ind`" in render_reports(chained)["split-leakage.md"]


@pytest.mark.parametrize(
    ("lower", "upper", "expected"),
    [
        (1.0, 0.0, "more than random splits (p < 0.001)"),
        (0.0, 1.0, "fewer than random splits (p < 0.001)"),
        (0.02, 0.99, "fewer than random splits (p = 0.020)"),
        (0.4, 0.6, "consistent with random splits"),
    ],
)
def test_the_reading_of_the_permutation_baseline(lower: float, upper: float, expected: str) -> None:
    baseline = PermutationBaseline(
        n_permutations=1000, observed=5, null_mean=5.0, null_sd=1.0, p_lower=lower, p_upper=upper
    )
    assert _reading(baseline) == expected


def test_slug() -> None:
    assert slug("(batch, side)") == "batch-side"
    assert slug("family A") == "family-a"
    assert slug("***") == "x"


def test_coinciding_review_and_family_thresholds_are_said_out_loud(result: AnalysisResult) -> None:
    t = result.audit.thresholds
    same = t.model_copy(update={"review": t.family})
    files = render_reports(result.audit.model_copy(update={"thresholds": same}))
    assert "The review and family thresholds coincide" in files["similarity-summary.md"]
    assert "review = family" in files["figures/percolation.svg"]
