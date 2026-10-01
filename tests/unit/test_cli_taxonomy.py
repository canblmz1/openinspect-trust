"""``openinspect taxonomy``: check, audit and report on a small synthetic repository."""

from __future__ import annotations

import shutil
from pathlib import Path

import pyarrow.parquet as pq
import pytest
import yaml
from typer.testing import CliRunner

from openinspect.cli import app
from openinspect.taxonomy.tables import AUDIT, MAP, REVIEW, read_audit
from tests.conftest import Repo
from tests.dedup_helpers import REPO_ROOT, Spec, make_image, write_items, write_records
from tests.taxonomy_helpers import DECLARED, manifest, taxonomy_data, write_annotations, write_m3

DEDUP = """schema_version: 1
preprocessing:
  version: v1
backend: cpu-fp32
default_model: stub
models:
  stub:
    model_id: stub/model
    revision: "0000000000000000000000000000000000000000"
    weights_file: model.safetensors
    weights_sha256: "0000000000000000000000000000000000000000000000000000000000000000"
    dim: 24
    licence: Apache-2.0
sources:
  src-a:
    acquisition_id: camera-a
  src-b:
    acquisition_id: camera-b
"""


def invoke(*args: str) -> object:
    return CliRunner().invoke(app, list(args))


@pytest.fixture
def m4(repo: Repo, tmp_path: Path) -> Repo:
    for slug, labels in DECLARED.items():
        repo.write_manifest(manifest(slug, labels))
    configs = repo.root / "configs"
    (configs / "dedup.yaml").write_text(DEDUP, encoding="utf-8")
    (configs / "taxonomy.yaml").write_text(
        yaml.safe_dump(taxonomy_data(), sort_keys=False), encoding="utf-8"
    )
    data = tmp_path / "data"
    a = [Spec(f"a{k}.png", make_image(k), "train" if k < 3 else "val") for k in range(4)]
    b = [Spec(f"b{k}.png", make_image(10 + k), "test") for k in range(3)]
    write_records(data, "src-a", write_items(data, "src-a", a))
    write_records(data, "src-b", write_items(data, "src-b", b))
    write_annotations(
        data,
        "src-a",
        [
            ("a0.png", 0, "SH", [2, 2, 20, 20]),
            ("a1.png", 0, "OP", [5, 5, 30, 12]),
            ("a2.png", 0, "SP", [1, 1, 9, 9]),
            ("a3.png", 0, "SH", [4, 4, 4, 30]),
        ],
    )
    write_annotations(
        data, "src-b", [("b0.png", 0, "short", [3, 3, 25, 25]), ("b1.png", 0, "burr", [1, 1, 6, 6])]
    )
    write_m3(
        repo.root,
        [
            {"source_a": "src-a", "image_a": "a0.png", "source_b": "src-a", "image_b": "a1.png"},
            {"source_a": "src-a", "image_a": "a0.png", "source_b": "src-b", "image_b": "b0.png"},
        ],
    )
    return repo


def test_check_passes_on_the_committed_repository() -> None:
    result = invoke("taxonomy", "check", "--repo-root", str(REPO_ROOT))
    assert result.exit_code == 0, result.output  # type: ignore[attr-defined]
    assert "benchmark classes: short, open, mouse_bite, spurious_copper" in result.output  # type: ignore[attr-defined]


def test_check_reports_an_unmapped_label(tmp_path: Path) -> None:
    root = tmp_path / "copy"
    shutil.copytree(REPO_ROOT / "manifests", root / "manifests")
    shutil.copytree(REPO_ROOT / "configs", root / "configs")
    path = root / "configs" / "taxonomy.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    del data["mappings"]["pcb-ind"]["stain"]
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    result = invoke("taxonomy", "check", "--repo-root", str(root))
    assert result.exit_code == 1  # type: ignore[attr-defined]
    assert "PROBLEM pcb-ind:stain is not mapped" in result.output  # type: ignore[attr-defined]


def test_check_needs_the_ingest_reports_and_a_valid_taxonomy(m4: Repo) -> None:
    missing = m4.cli("taxonomy", "check")
    assert missing.exit_code == 1
    assert "cannot read its ingest report" in missing.output
    (m4.root / "configs" / "taxonomy.yaml").write_text("schema_version: 9\n", encoding="utf-8")
    broken = m4.cli("taxonomy", "check")
    assert broken.exit_code == 1
    assert "invalid configs/taxonomy.yaml" in broken.output


def test_audit_writes_the_map_the_queue_the_audit_and_the_reports(m4: Repo, tmp_path: Path) -> None:
    out, reports = tmp_path / "artifacts", tmp_path / "reports"
    data = str(tmp_path / "data")
    result = m4.cli(
        "taxonomy",
        "audit",
        "--all",
        "--out",
        str(out),
        "--reports",
        str(reports),
        "--data-dir",
        data,
    )
    assert result.exit_code == 0, result.output
    assert "src-a: 4 images, 3 eligible, 1 excluded, 0 negatives" in result.output
    assert "src-b: 3 images, 1 eligible, 1 excluded, 1 negatives" in result.output
    audit = read_audit(out / AUDIT)
    assert audit.run.code_commit is None  # not a git repository
    assert set(audit.artifacts) == {MAP, REVIEW}
    assert audit.human_validation.queued == 3
    assert audit.human_validation.reviewed == 0
    assert set(audit.inputs) == {
        "records/src-a/images.jsonl",
        "records/src-a/annotations.jsonl",
        "records/src-b/images.jsonl",
        "records/src-b/annotations.jsonl",
        "artifacts/m3/duplicate-pairs.parquet",
        "artifacts/m3/thresholds.json",
    }
    table = pq.read_table(out / MAP).to_pylist()
    assert [(r["image_id"], r["original_label"], r["normalized_label"]) for r in table] == [
        ("a0.png", "SH", "short"),
        ("a1.png", "OP", "open"),
        ("a2.png", "SP", "spur"),
        ("a3.png", "SH", "short"),
        ("b0.png", "short", "short"),
        ("b1.png", "burr", "burr"),
    ]
    queue = (out / REVIEW).read_text(encoding="utf-8")
    assert "zero_area_box" in queue
    assert "near_duplicate_label_conflict" in queue
    assert "mapping_ambiguity" in queue
    rendered = {p.name: p.read_bytes() for p in reports.iterdir()}
    again = tmp_path / "again"
    report = m4.cli("taxonomy", "report", "--out", str(out), "--reports", str(again))
    assert report.exit_code == 0, report.output
    assert {p.name: p.read_bytes() for p in again.iterdir()} == rendered

    path = m4.root / "configs" / "taxonomy.yaml"
    path.write_text(path.read_text(encoding="utf-8") + "# edited\n", encoding="utf-8")
    stale = m4.cli("taxonomy", "report", "--out", str(out), "--reports", str(again))
    assert stale.exit_code == 1
    assert "changed since the audit" in stale.output
    unreadable = m4.cli("taxonomy", "report", "--out", str(tmp_path / "nowhere"))
    assert unreadable.exit_code == 1
    assert "cannot read audit.json" in unreadable.output


def test_audit_refuses_unmapped_labels_and_missing_m3_artifacts(m4: Repo, tmp_path: Path) -> None:
    data = tmp_path / "data"
    out = ["--out", str(tmp_path / "a"), "--reports", str(tmp_path / "r"), "--data-dir", str(data)]
    (m4.root / "artifacts" / "m3" / "thresholds.json").unlink()
    no_m3 = m4.cli("taxonomy", "audit", "--all", *out)
    assert no_m3.exit_code == 1
    assert "thresholds.json" in no_m3.output
    write_m3(m4.root, [])
    write_annotations(data, "src-b", [("b0.png", 0, "whisker", [3, 3, 25, 25])])
    unmapped = m4.cli("taxonomy", "audit", "--all", *out)
    assert unmapped.exit_code == 1
    assert "PROBLEM src-b:whisker is not mapped" in unmapped.output
    taxonomy = taxonomy_data()
    for labels in taxonomy["mappings"].values():
        for mapping in labels.values():
            if mapping["status"] in ("EXACT", "COMPATIBLE"):
                mapping["status"] = "SOURCE_SPECIFIC"
    taxonomy["mappings"]["src-b"]["whisker"] = {
        "normalized_label": "burr",
        "status": "SOURCE_SPECIFIC",
        "evidence": "a whisker of copper",
    }
    m4.write_manifest(manifest("src-b", [*DECLARED["src-b"], "whisker"]))
    (m4.root / "configs" / "taxonomy.yaml").write_text(
        yaml.safe_dump(taxonomy, sort_keys=False), encoding="utf-8"
    )
    no_benchmark = m4.cli("taxonomy", "audit", "--all", *out)
    assert no_benchmark.exit_code == 1
    assert "no benchmark class" in no_benchmark.output
    (m4.root / "configs" / "taxonomy.yaml").unlink()
    gone = m4.cli("taxonomy", "audit", "--all", *out)
    assert gone.exit_code == 1
    assert "cannot read configs/taxonomy.yaml" in gone.output
