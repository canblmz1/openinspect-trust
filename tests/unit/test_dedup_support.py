from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from defusedxml import ElementTree

from openinspect.dedup.config import ConfigError, load_config
from openinspect.dedup.embedder import EmbedderError, verify_weights
from openinspect.dedup.inventory import InventoryError, load_items
from openinspect.dedup.perf import (
    StageTiming,
    append_run,
    build_performance,
    code_version,
    cpu_name,
    peak_memory_bytes,
    read_runs,
    runs_file,
    timed,
)
from openinspect.dedup.review import (
    PACK,
    ReviewError,
    Thumbnails,
    sample_groups,
    write_review_pack,
)
from openinspect.dedup.svg import Bars, Marker, Series, _nice_max, bar_chart, line_chart
from openinspect.dedup.tables import REVIEW_COLUMNS
from openinspect.provenance.records import ImageRecord
from tests.dedup_helpers import Spec, corrupt_copy, make_image, write_items, write_records

CONFIG = """schema_version: 1
preprocessing:
  version: v1
backend: cpu-fp32
default_model: stub
models:
  stub:
    model_id: stub/model
    revision: "0000000000000000000000000000000000000000"
    weights_file: model.safetensors
    weights_sha256: "{sha}"
    dim: 24
    licence: Apache-2.0
"""


# --------------------------------------------------------------------------- review


def review_row(pair_id: str, a: str, b: str, source: str = "src") -> dict[str, str]:
    row = dict.fromkeys(REVIEW_COLUMNS, "")
    row.update(
        {
            "pair_id": pair_id,
            "stratum": f"within:{source}|NEAR_DUPLICATE|cross-split|same-group",
            "source": source,
            "machine_category": "NEAR_DUPLICATE",
            "cosine": "0.990000",
            "phash_distance": "2",
            "dhash_distance": "3",
            "source_a": source,
            "image_a": a,
            "split_a": "train",
            "metadata_group_a": "g1",
            "metadata_subgroup_a": "g1_b",
            "source_b": source,
            "image_b": b,
            "split_b": "val",
            "component_near": "VSG-near-00001",
            "component_family": "VSG-family-00001",
        }
    )
    return row


def test_the_review_pack_embeds_both_images_and_marks_missing_ones(tmp_path: Path) -> None:
    data = tmp_path / "data"
    items = write_items(
        data,
        "src",
        [Spec("a.png", make_image(1)), Spec("b.png", make_image(2)), Spec("c.png", make_image(3))],
    )
    broken = corrupt_copy(items[2])
    rows = [review_row("R-0001", "a.png", "b.png"), review_row("R-0002", "a.png", "gone.png")]
    groups = [
        {
            "group_id": "VSG-family-00001",
            "level": "family",
            "sources": ["src"],
            "members": ["src:a.png", "src:b.png", "src:c.png"],
            "splits": ["src:train"],
            "all_pairs_min_similarity": 0.93,
            "chaining_gap": 0.01,
        },
    ]
    path = write_review_pack(rows, [items[0], items[1], broken], tmp_path / "pack", groups=groups)
    assert path.name == PACK
    html = path.read_text(encoding="utf-8")
    # R-0001 shows a and b, R-0002 shows a again next to a placeholder, the strip shows a and b
    assert html.count("data:image/jpeg;base64,") == 5
    assert "image not available: gone.png" in html
    assert "image not available: src:c.png" in html  # undecodable file
    assert "R-0002" in html
    assert "VSG-family-00001" in html
    assert "min pairwise cosine 0.930" in html
    assert "not proof of the same physical board" in html


def test_an_empty_review_queue_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ReviewError):
        write_review_pack([], [], tmp_path)


def test_thumbnails_are_computed_once_per_image(tmp_path: Path) -> None:
    (item,) = write_items(tmp_path, "src", [Spec("a.png", make_image(4, size=(400, 300)))])
    thumbs = Thumbnails(size=64)
    first = thumbs.of(item)
    assert first is not None
    item.path.unlink()  # a second call must not read the file again
    assert thumbs.of(item) == first
    assert thumbs.of(None) is None


def test_sample_groups_is_seeded_and_keeps_one_level_and_source() -> None:
    groups = [
        {
            "group_id": f"G{k:02d}",
            "level": "family" if k % 3 else "near",
            "sources": ["a"] if k % 2 else ["b"],
            "members": [],
        }
        for k in range(30)
    ] + [{"group_id": "X", "level": "family", "sources": ["a", "b"], "members": []}]
    first = sample_groups(groups, per_source=3, seed=0)
    assert first == sample_groups(groups, per_source=3, seed=0)
    assert len(first) == 6
    assert all(g["level"] == "family" for g in first)
    assert all(g["group_id"] != "X" for g in first)
    assert sample_groups(groups, per_source=3, seed=1) != first


# ------------------------------------------------------------------------------ svg


def test_line_chart_is_well_formed_and_skips_markers_outside_the_range() -> None:
    svg = line_chart(
        "t <&>",
        "x",
        "y",
        [Series("a", [(0.0, 0.0), (1.0, 1.0)]), Series("b", [], dashed=True)],
        x_range=(0.0, 1.0),
        y_range=(0.0, 1.0),
        markers=[Marker(0.5, "half"), Marker(2.0, "outside")],
    )
    root = ElementTree.fromstring(svg)
    assert root.tag.endswith("svg")
    assert "half" in svg
    assert "outside" not in svg
    assert "t &lt;&amp;&gt;" in svg
    assert svg.count("<polyline") == 1  # the empty series has a legend but no line


def test_bar_chart_starts_at_zero_and_labels_every_bar() -> None:
    svg = bar_chart("bars", "x", "y", ["one", "two"], [Bars("a", [3.0, 0.0]), Bars("b", [7.0])])
    ElementTree.fromstring(svg)
    assert svg.count("<rect") == 1 + 4 + 2  # background, four bars, two legend keys
    assert ">7<" in svg
    assert ">10<" in svg  # the axis maximum is rounded up to 10


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.0, 1.0), (0.7, 1.0), (3.0, 5.0), (7.0, 10.0), (120.0, 200.0), (1.0, 1.0)],
)
def test_nice_axis_maximum(value: float, expected: float) -> None:
    assert _nice_max(value) == expected


# ----------------------------------------------------------------------------- perf


def test_timed_records_seconds_and_peak_memory() -> None:
    sink: list[StageTiming] = []
    with timed("stage", sink):
        _ = [0] * 1000
    (timing,) = sink
    assert timing.stage == "stage"
    assert timing.seconds >= 0
    peak = peak_memory_bytes()
    assert peak is not None
    assert peak > 1_000_000
    name = cpu_name()
    assert name is None or len(name) > 3


def test_a_failing_stage_is_still_timed() -> None:
    sink: list[StageTiming] = []
    with pytest.raises(ZeroDivisionError), timed("broken", sink):
        _ = 1 / 0
    assert [t.stage for t in sink] == ["broken"]


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_code_version_reads_head_and_whether_the_tree_is_dirty(tmp_path: Path) -> None:
    assert code_version(tmp_path) == (None, None)  # not a repository
    git = shutil.which("git") or "git"

    def run(*args: str) -> None:
        subprocess.run([git, *args], cwd=tmp_path, check=True, capture_output=True)

    run("init", "-q")
    run("config", "user.email", "test@example.org")
    run("config", "user.name", "Test")
    (tmp_path / "file.txt").write_text("one\n", encoding="utf-8")
    run("add", "file.txt")
    run("commit", "-q", "-m", "first")
    head, dirty = code_version(tmp_path)
    assert head is not None
    assert len(head) == 40
    assert dirty is False
    (tmp_path / "file.txt").write_text("two\n", encoding="utf-8")
    assert code_version(tmp_path) == (head, True)
    (tmp_path / "untracked.txt").write_text("x\n", encoding="utf-8")
    (tmp_path / "file.txt").write_text("one\n", encoding="utf-8")
    assert code_version(tmp_path) == (head, False)  # untracked files do not count


def test_run_records_append_and_read_back(tmp_path: Path) -> None:
    assert read_runs(tmp_path, "features") == []
    append_run(tmp_path, "features", {"embedded": 3, "wall_seconds": 1.5})
    append_run(tmp_path, "features", {"embedded": 0})
    path = runs_file(tmp_path, "features")
    path.write_text(path.read_text(encoding="utf-8") + "\n[1, 2]\n", encoding="utf-8")
    assert read_runs(tmp_path, "features") == [
        {"embedded": 3, "wall_seconds": 1.5},
        {"embedded": 0},
    ]


def test_build_performance_uses_the_run_that_filled_the_cache() -> None:
    runs: list[dict[str, object]] = [
        {"embedded": 0, "wall_seconds": 2.0},
        {
            "embedded": 900,
            "wall_seconds": 90.0,
            "images_per_second": 10.0,
            "model_images_per_second": 12.5,
            "peak_ram_bytes": 4_000,
            "note": "from the log",
        },
    ]
    perf = build_performance(
        [StageTiming("calibration", 1.0, 5_000)],
        features_runs=runs,
        synthetic_runs=[{"embedded": 30, "wall_seconds": 3.0, "peak_ram_bytes": None}],
        cache_files=900,
        cache_bytes=1_000_000,
        dim=384,
    )
    assert [s.stage for s in perf.stages] == [
        "embeddings (cache build)",
        "synthetic copies",
        "calibration",
    ]
    assert perf.stages[0].note == "from the log"
    assert perf.embed_images_per_second == 10.0
    assert perf.embed_model_images_per_second == 12.5
    assert perf.total_seconds == 94.0
    assert perf.peak_ram_bytes == 5_000
    assert perf.cache_logical_bytes == 900 * 384 * 4
    empty = build_performance(
        [], features_runs=[], synthetic_runs=[], cache_files=0, cache_bytes=0, dim=8
    )
    assert empty.stages == []
    assert empty.peak_ram_bytes is None
    assert empty.embed_images_per_second is None


# --------------------------------------------------------------- config, inventory


def test_the_config_loads_and_refuses_bad_files(tmp_path: Path) -> None:
    configs = tmp_path / "configs"
    configs.mkdir()
    with pytest.raises(ConfigError, match="cannot read"):
        load_config(tmp_path)
    (configs / "dedup.yaml").write_text("a: [b\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="cannot read"):
        load_config(tmp_path)
    (configs / "dedup.yaml").write_text(
        CONFIG.format(sha="0" * 64).replace("default_model: stub", "default_model: other"),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="invalid"):
        load_config(tmp_path)
    (configs / "dedup.yaml").write_text(CONFIG.format(sha="0" * 64), encoding="utf-8")
    config = load_config(tmp_path)
    key, entry = config.model()
    assert key == "stub"
    assert entry.dim == 24
    with pytest.raises(ConfigError, match="unknown model"):
        config.model("missing")


def test_the_repository_config_pins_the_models() -> None:
    config = load_config(Path(__file__).resolve().parents[2])
    _, entry = config.model()
    assert entry.model_id == "facebook/dinov2-small"
    assert len(entry.revision) == 40
    assert config.preprocessing.version == "v1"


def test_load_items_lists_undecodable_images_apart(tmp_path: Path) -> None:
    with pytest.raises(InventoryError, match="no image records"):
        load_items(tmp_path, ["src"])
    items = write_items(
        tmp_path,
        "src",
        [Spec("b.png", make_image(1), "train", "g", "g_1"), Spec("a.png", make_image(2))],
    )
    write_records(tmp_path, "src", items)
    records = tmp_path / "records" / "src" / "images.jsonl"
    lines = records.read_text(encoding="utf-8").splitlines()
    bad = ImageRecord.model_validate_json(lines[0]).model_copy(
        update={"source_item_id": "broken.png", "decode_ok": False, "decode_error": "truncated"}
    )
    records.write_text("\n".join([*lines, bad.model_dump_json()]) + "\n", encoding="utf-8")
    loaded, skipped = load_items(tmp_path, ["src"])
    assert [item.item_id for item in loaded] == ["a.png", "b.png"]
    assert loaded[1].group_id == "g"
    assert loaded[1].subgroup_id == "g_1"
    assert loaded[1].dhash is not None
    assert [(s.item_id, s.stage, s.error) for s in skipped] == [
        ("broken.png", "ingest", "truncated")
    ]


def test_python_is_what_ci_runs() -> None:
    assert sys.version_info >= (3, 12)


def test_weights_are_refused_unless_their_hash_matches(tmp_path: Path) -> None:
    weights = tmp_path / "model.safetensors"
    weights.write_bytes(b"weights")
    verify_weights(weights, hashlib.sha256(b"weights").hexdigest())
    with pytest.raises(EmbedderError, match="refusing to load unverified weights"):
        verify_weights(weights, "0" * 64)
