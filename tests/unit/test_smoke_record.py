from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import yaml

from openinspect.release.smoke_record import (
    Generator,
    SmokeRecordError,
    check_zip,
    load_expected,
    load_observation,
    make_record,
    render,
)
from tests.readiness_helpers import yolo_zip

OBSERVED = {
    "schema_version": 1,
    "observed_on": "2026-10-01",
    "observer": "maintainer",
    "platform": "EVREN web UI",
    "dataset": {"name": "d", "visibility": "private", "licence": "CC BY 4.0", "tags": ["t"]},
    "upload": {
        "package": "p.zip",
        "format_detected": "YOLO Detection",
        "import_completed": True,
        "auto_split_used": False,
    },
    "import_summary": {"images": 3, "annotations": 4, "classes": 2, "unlabelled_images": 0},
    "splits_shown": {"train": 1, "val": 1, "test": 1},
    "split_labels_ui": {"train": "Eğitim", "val": "Doğrulama", "test": "Test"},
    "classes_shown": {"short": 3, "open": 1},
    "items_checked": [
        {
            "file_name": "OI_x_1.png",
            "split_ui": "Test",
            "split": "test",
            "labels_shown": ["short"],
            "boxes_visually_aligned": True,
        }
    ],
    "version": {
        "name": "v",
        "description": "d",
        "options_left_off": ["x"],
        "message_ui": "ok",
        "frozen": True,
        "summary": {"items": 3, "labelled": 3, "annotations": 4, "classes": 2},
        "splits": {"train": 1, "val": 1, "test": 1},
    },
    "dataset_health": {
        "grade": "A",
        "score": 81,
        "label_ui": "Mükemmel",
        "subscores": {"data_volume": 12},
        "warning": "few images",
    },
    "training_started": False,
}

ROWS = [
    ("OI_x_0", "OI_x_0.png", "train", "short;open", 2),
    ("OI_x_1", "OI_x_1.png", "test", "short", 1),
    ("OI_x_2", "OI_x_2.png", "val", "short", 1),
]


def setup_dir(tmp_path: Path, observed: dict[str, object] | None = None) -> tuple[Path, Path]:
    smoke = tmp_path / "smoke"
    smoke.mkdir(parents=True)
    (smoke / "observed.yaml").write_text(
        yaml.safe_dump(observed or OBSERVED, allow_unicode=True), encoding="utf-8"
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["global_id", "file_name", "split", "source", "classes", "boxes", "sha256"])
    for gid, name, split, classes, count in ROWS:
        writer.writerow([gid, name, split, "x", classes, count, "0" * 64])
    (smoke / "expected-splits.csv").write_text(buffer.getvalue(), encoding="utf-8")
    package = yolo_zip(
        {
            "train/OI_x_0": "0 0.5 0.5 0.1 0.1\n1 0.2 0.2 0.1 0.1\n",
            "test/OI_x_1": "0 0.5 0.5 0.1 0.1\n",
            "val/OI_x_2": "0 0.5 0.5 0.1 0.1\n",
        },
        data_yaml="path: .\nnc: 2\nnames:\n  0: short\n  1: open\n",
    )
    zip_path = tmp_path / "p.zip"
    zip_path.write_bytes(package)
    record = {
        "package": "p.zip",
        "zip_sha256": __import__("hashlib").sha256(package).hexdigest(),
        "format": "YOLO Detection",
        "classes": {"0": "short", "1": "open"},
    }
    (smoke / "smoke.json").write_text(json.dumps(record), encoding="utf-8")
    boxes = tmp_path / "annotations.parquet"
    pq.write_table(
        pa.table(
            {
                "global_id": ["OI_x_0", "OI_x_0", "OI_x_1", "OI_x_2", "OI_other"],
                "normalized_label": ["short", "open", "short", "short", "open"],
            }
        ),
        boxes,
    )
    return smoke, boxes


def build(tmp_path: Path, observed: dict[str, object] | None = None, *, with_zip: bool = True):  # type: ignore[no-untyped-def]
    smoke, boxes = setup_dir(tmp_path, observed)
    obs = load_observation(smoke / "observed.yaml")
    exp = load_expected(smoke, boxes)
    found = check_zip(tmp_path / "p.zip", exp) if with_zip else None
    return make_record(
        obs,
        exp,
        found,
        inputs={"x": "y"},
        generator=Generator(command="c", code_commit="abc", code_dirty=False),
    )


def test_matching_observations_pass(tmp_path: Path) -> None:
    record = build(tmp_path)
    assert record.verdict == "PASS"
    assert all(c.result == "MATCH" for c in record.checks)
    assert record.zip_check is not None
    assert record.zip_check.matches_record
    assert record.zip_check.boxes_per_class == {"open": 1, "short": 3}
    statuses = {s.status for s in record.statements}
    assert {"OBSERVED_IN_EVREN", "NOT_TESTED", "UNKNOWN"} <= statuses
    text = render(record, "smoke")
    assert "## Verdict: **PASS**" in text
    assert "not an OpenInspect-Trust assurance result" in text


def test_a_changed_split_count_fails(tmp_path: Path) -> None:
    observed = json.loads(json.dumps(OBSERVED))
    observed["splits_shown"] = {"train": 2, "val": 0, "test": 1}
    record = build(tmp_path, observed)
    assert record.verdict == "FAIL"
    bad = [c for c in record.checks if c.result == "MISMATCH"]
    assert [c.capability for c in bad] == [
        "supplied train/val/test split kept on import (aggregate counts)"
    ]


def test_an_item_in_the_wrong_split_or_unknown_fails(tmp_path: Path) -> None:
    observed = json.loads(json.dumps(OBSERVED))
    observed["items_checked"][0]["split"] = "train"
    assert build(tmp_path / "a", observed).verdict == "FAIL"
    observed = json.loads(json.dumps(OBSERVED))
    observed["items_checked"][0]["file_name"] = "OI_unknown.png"
    record = build(tmp_path / "b", observed)
    assert any(c.expected == "not in the package" for c in record.checks)


def test_auto_split_alone_fails_the_test(tmp_path: Path) -> None:
    observed = json.loads(json.dumps(OBSERVED))
    observed["upload"]["auto_split_used"] = True
    assert build(tmp_path, observed).verdict == "FAIL"


def test_without_the_zip_only_the_observations_are_compared(tmp_path: Path) -> None:
    record = build(tmp_path, with_zip=False)
    assert record.verdict == "PASS"
    assert record.zip_check is None
    assert all(c.status == "OBSERVED_IN_EVREN" for c in record.checks)


def test_unreadable_inputs_are_errors(tmp_path: Path) -> None:
    (tmp_path / "bad.yaml").write_text("schema_version: 1\n", encoding="utf-8")
    with pytest.raises(SmokeRecordError, match="cannot read"):
        load_observation(tmp_path / "bad.yaml")
    with pytest.raises(SmokeRecordError, match="committed smoke expectation"):
        load_expected(tmp_path, tmp_path / "missing.parquet")
