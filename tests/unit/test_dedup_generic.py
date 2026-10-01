"""The core knows generic keys only, and a representation change is compared, not assumed."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import numpy as np
import pytest

from openinspect.dedup.analysis import (
    AnalysisError,
    AnalysisResult,
    PoolSpec,
    Settings,
    make_views,
    metadata_integrity,
    robustness,
    run_analysis,
)
from openinspect.dedup.compute import FeatureSet
from openinspect.dedup.inventory import ImageItem
from openinspect.dedup.report import render_reports
from openinspect.dedup.synthetic import SyntheticPair
from openinspect.dedup.thresholds import CalibrationError
from tests.dedup_helpers import (
    NOT_REVIEWED,
    REPO_ROOT,
    Clustered,
    clustered_features,
    make_spec,
    repository_settings,
)

SPEC = make_spec(dim=16)


@pytest.fixture(scope="module")
def clustered() -> Clustered:
    return clustered_features()


@pytest.fixture(scope="module")
def primary(clustered: Clustered) -> AnalysisResult:
    return run_analysis(
        clustered.features,
        clustered.synthetic,
        spec=SPEC,
        weights_sha256="0" * 64,
        settings=repository_settings(permutations=100, resamples=100),
    )


def perturbed(features: FeatureSet, noise: float, seed: int = 7) -> FeatureSet:
    rng = np.random.default_rng(seed)
    moved = features.vectors + noise * rng.standard_normal(features.vectors.shape).astype(
        np.float32
    )
    moved /= np.linalg.norm(moved, axis=1, keepdims=True)
    return FeatureSet(features.items, moved.astype(np.float32), features.phash, features.dhash)


def test_a_representation_compared_with_itself_agrees_fully(primary: AnalysisResult) -> None:
    check = robustness(primary, primary, other_model="same")
    assert {(row.source, row.level) for row in check.rows} == {
        (s, level)
        for s in ("dspcbsd-plus", "pcb-defect", "pcb-ind")
        for level in ("near", "family")
    }
    for row in check.rows:
        assert row.adjusted_rand == 1.0
        assert row.reading_primary == row.reading_other
        assert row.groups_primary == row.groups_other
    assert set(check.top1_agreement.values()) == {1.0}


def test_a_changed_representation_is_measured(
    clustered: Clustered, primary: AnalysisResult
) -> None:
    other = run_analysis(
        perturbed(clustered.features, 0.05),
        clustered.synthetic,
        spec=make_spec(name="other", dim=16),
        weights_sha256="1" * 64,
        settings=repository_settings(permutations=100, resamples=100),
    )
    check = robustness(primary, other, other_model="other/model@000000000000")
    assert check.other_thresholds == other.audit.thresholds
    assert check.other_synthetic_recall == other.audit.synthetic_recall
    assert all(row.adjusted_rand is not None for row in check.rows)
    assert all(0.0 <= value <= 1.0 for value in check.top1_agreement.values())
    ind = next(r for r in check.rows if r.source == "pcb-ind" and r.level == "family")
    assert ind.exposed_primary is not None
    assert ind.reading_primary is not None
    defect = next(r for r in check.rows if r.source == "pcb-defect")
    assert defect.crossing_primary is None  # no split
    files = render_reports(primary.audit.model_copy(update={"robustness": check}), NOT_REVIEWED)
    assert "## Agreement of the two groupings" in files["representation-robustness.md"]
    assert "source and level pairs" in files["representation-robustness.md"]
    assert "other/model@000000000000" in files["limitations.md"]
    assert "The size of the leakage is another matter" in files["representation-robustness.md"]
    assert (
        "Synthetic recall at each representation's final near threshold"
        in files["representation-robustness.md"]
    )
    assert "so the direction of the findings holds" in files["limitations.md"]


def test_audits_of_different_images_are_not_compared(
    clustered: Clustered, primary: AnalysisResult
) -> None:
    fewer = FeatureSet(
        clustered.features.items[1:],
        clustered.features.vectors[1:],
        clustered.features.phash[1:],
        clustered.features.dhash[1:],
    )
    other = run_analysis(
        fewer,
        clustered.synthetic,
        spec=SPEC,
        weights_sha256="0" * 64,
        settings=repository_settings(permutations=10, resamples=10),
    )
    with pytest.raises(AnalysisError, match="same images"):
        robustness(primary, other, other_model="x")


def test_metadata_integrity_counts_key_values_across_splits(clustered: Clustered) -> None:
    rows = metadata_integrity(make_views(clustered.features), repository_settings())
    by = {(r.source, r.key): r for r in rows}
    assert set(by) == {("pcb-ind", "group_id"), ("pcb-ind", "subgroup_id")}  # the only keyed split
    assert by[("pcb-ind", "group_id")].key_name == "batch"
    assert by[("pcb-ind", "group_id")].values == 6
    assert by[("pcb-ind", "group_id")].crossing == 1  # batch 0005: one side in train, one in val
    assert by[("pcb-ind", "group_id")].images_in_crossing == 10
    assert by[("pcb-ind", "subgroup_id")].crossing == 0


def generic_features() -> tuple[FeatureSet, list[SyntheticPair]]:
    """Two sources with made-up names and keys: nothing domain-specific anywhere."""
    rng = np.random.default_rng(3)
    items: list[ImageItem] = []
    rows = []
    for lot in range(8):
        centre = rng.standard_normal(12)
        for k in range(6):
            split = "train" if lot < 6 else "test"
            item_id = f"lot{lot}/{k}.png"
            items.append(
                ImageItem(
                    "line-a",
                    item_id,
                    Path("missing") / item_id,
                    hashlib.sha256(item_id.encode()).hexdigest(),
                    split,
                    f"lot{lot}",
                    f"lot{lot}-cam{k % 2}",
                    1,
                    None,
                    32,
                    32,
                    "camera-rig",
                )
            )
            rows.append(centre + 0.05 * rng.standard_normal(12))
    for k in range(10):
        item_id = f"b/{k}.png"
        items.append(
            ImageItem(
                "line-b",
                item_id,
                Path(item_id),
                hashlib.sha256(item_id.encode()).hexdigest(),
                None,
                None,
                None,
                1,
                None,
                64,
                64,
                "phone",
            )
        )
        rows.append(rng.standard_normal(12))
    vectors = np.array(rows, dtype=np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    hashes = rng.integers(0, 2**63, size=len(items), dtype=np.int64).astype(np.uint64)
    features = FeatureSet(items, vectors, hashes, hashes.copy())
    synthetic = [
        SyntheticPair(
            item.source, item.item_id, item.sha256, "blur", "photometric", True, 0.99, 1, 1
        )
        for item in items[::5]
    ]
    return features, synthetic


def test_the_core_runs_on_generic_keys_from_any_domain() -> None:
    features, synthetic = generic_features()
    settings = Settings(
        permutations=50,
        resamples=50,
        pools={"line-a": (PoolSpec("lot", "group_id", "group_id", True),)},
        key_names={"line-a": ("production lot", "lot and camera")},
        acquisition={"line-a": "camera-rig", "line-b": "phone"},
    )
    result = run_analysis(
        features, synthetic, spec=make_spec(dim=12), weights_sha256="0" * 64, settings=settings
    )
    audit = result.audit
    assert [(p.source, p.pool) for p in audit.pools] == [("line-a", "lot")]
    assert {s.source: s.acquisition_id for s in audit.run.sources} == {
        "line-a": "camera-rig",
        "line-b": "phone",
    }
    assert {s.source: s.group_key for s in audit.run.sources} == {
        "line-a": "production lot",
        "line-b": None,
    }
    overlap = next(o for level in audit.levels for o in level.key_overlap)
    assert (overlap.key_group_name, overlap.key_subgroup_name) == (
        "production lot",
        "lot and camera",
    )
    text = "".join(render_reports(audit, NOT_REVIEWED).values()).lower()
    assert "pcb" not in text
    assert "`line-a`: its own keys (production lot; lot and camera)" in text


def test_without_pools_there_is_no_calibration() -> None:
    features, synthetic = generic_features()
    with pytest.raises(CalibrationError, match="no labelled pool"):
        run_analysis(
            features,
            synthetic,
            spec=make_spec(dim=12),
            weights_sha256="0" * 64,
            settings=Settings(),
        )


def test_no_dataset_is_special_cased_in_the_core() -> None:
    """No string literal of the generic modules names one of the datasets."""
    modules = sorted((REPO_ROOT / "src" / "openinspect" / "dedup").glob("*.py"))
    modules.append(REPO_ROOT / "src" / "openinspect" / "assurance.py")
    offenders = []
    for path in modules:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                lowered = node.value.lower()
                if "pcb-" in lowered or "dspcbsd" in lowered or "deeppcb" in lowered:
                    offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []
