"""The EVREN import smoke test (Milestone 6): what was observed, against what was committed.

The maintainer imported the smoke package in the EVREN web UI and recorded what the UI showed
(``evren-smoke/observed.yaml``). This module compares every observation with the expectation that
was committed before the upload (``expected-splits.csv``, ``smoke.json``, the release's box table)
and, when the data directory is available, with the ZIP itself. It keeps four kinds of statement
apart: observed in EVREN, verified locally, not tested, unknown. It never upgrades an observation
of a few items into a claim about all of them.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from collections import Counter
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Literal

import pyarrow.parquet as pq
import yaml
from pydantic import Field, ValidationError

from openinspect.provenance.schema import StrictModel

Split = Literal["train", "val", "test"]
SPLITS: tuple[Split, ...] = ("train", "val", "test")
Status = Literal["OBSERVED_IN_EVREN", "LOCALLY_VERIFIED", "NOT_TESTED", "UNKNOWN"]
Result = Literal["MATCH", "MISMATCH", "N/A"]
OBSERVED = "observed.yaml"
# the order of EVREN's Dataset Health panel (the record stores its keys sorted)
SUBSCORES = ("labelling_completion", "split_distribution", "class_balance", "data_volume")


class SmokeRecordError(Exception):
    """The observation file or the committed expectation cannot be read."""


# ------------------------------------------------------------------------- observation


class ObservedDataset(StrictModel):
    name: str
    visibility: str
    licence: str
    tags: list[str]


class ObservedUpload(StrictModel):
    package: str
    format_detected: str
    import_completed: bool
    auto_split_used: bool


class ImportSummary(StrictModel):
    images: int = Field(ge=0)
    annotations: int = Field(ge=0)
    classes: int = Field(ge=0)
    unlabelled_images: int = Field(ge=0)


class ObservedItem(StrictModel):
    file_name: str
    split_ui: str
    split: Split
    labels_shown: list[str]
    boxes_visually_aligned: bool


class VersionSummary(StrictModel):
    items: int = Field(ge=0)
    labelled: int = Field(ge=0)
    annotations: int = Field(ge=0)
    classes: int = Field(ge=0)


class ObservedVersion(StrictModel):
    name: str
    description: str
    options_left_off: list[str]
    message_ui: str
    frozen: bool
    summary: VersionSummary
    splits: dict[Split, int]


class DatasetHealth(StrictModel):
    grade: str
    score: int
    label_ui: str
    subscores: dict[str, int]
    warning: str


class Observation(StrictModel):
    schema_version: int
    observed_on: date
    observer: str
    platform: str
    dataset: ObservedDataset
    upload: ObservedUpload
    import_summary: ImportSummary
    splits_shown: dict[Split, int]
    split_labels_ui: dict[Split, str]
    classes_shown: dict[str, int]
    items_checked: list[ObservedItem]
    version: ObservedVersion
    dataset_health: DatasetHealth
    training_started: bool


def load_observation(path: Path) -> Observation:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return Observation.model_validate(raw)
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise SmokeRecordError(f"cannot read {path.name}: {exc}") from exc


# ------------------------------------------------------------------------- expectation


class ExpectedItem(StrictModel):
    global_id: str
    file_name: str
    split: Split
    classes: list[str]
    boxes: int


class Expected(StrictModel):
    """What the package holds, from files committed before the upload."""

    package: str
    zip_sha256: str
    format: str
    class_names: list[str]
    items: list[ExpectedItem]
    boxes_per_class: dict[str, int]

    @property
    def splits(self) -> dict[str, int]:
        counts = Counter(i.split for i in self.items)
        return {s: counts[s] for s in SPLITS}

    @property
    def annotations(self) -> int:
        return sum(i.boxes for i in self.items)


def load_expected(smoke_dir: Path, annotations_file: Path) -> Expected:
    try:
        record = json.loads((smoke_dir / "smoke.json").read_text(encoding="utf-8"))
        rows = list(
            csv.DictReader(
                io.StringIO((smoke_dir / "expected-splits.csv").read_text(encoding="utf-8"))
            )
        )
        boxes = pq.read_table(annotations_file, columns=["global_id", "normalized_label"])
    except (OSError, ValueError) as exc:
        raise SmokeRecordError(f"cannot read the committed smoke expectation: {exc}") from exc
    items = [
        ExpectedItem.model_validate(
            {
                "global_id": r["global_id"],
                "file_name": r["file_name"],
                "split": r["split"],
                "classes": [c for c in r["classes"].split(";") if c],
                "boxes": int(r["boxes"]),
            }
        )
        for r in rows
    ]
    ids = {i.global_id for i in items}
    per_class: Counter[str] = Counter(
        label
        for gid, label in zip(
            boxes.column("global_id").to_pylist(),
            boxes.column("normalized_label").to_pylist(),
            strict=True,
        )
        if gid in ids
    )
    names = [record["classes"][str(k)] for k in range(len(record["classes"]))]
    return Expected(
        package=str(record["package"]),
        zip_sha256=str(record["zip_sha256"]),
        format=str(record["format"]),
        class_names=names,
        items=items,
        boxes_per_class={name: per_class[name] for name in names},
    )


# ------------------------------------------------------------------------------ the ZIP


class ZipCheck(StrictModel):
    """The archive on disk, read member by member (no OpenInspect parsing beyond counting)."""

    sha256: str
    matches_record: bool
    images: int
    label_files: int
    annotations: int
    boxes_per_class: dict[str, int]
    splits: dict[str, int]
    data_yaml_names: list[str]


def check_zip(path: Path, expected: Expected) -> ZipCheck:
    data = path.read_bytes()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        images = [n for n in names if n.startswith("images/") and not n.endswith("/")]
        labels = [n for n in names if n.startswith("labels/") and n.endswith(".txt")]
        per_class: Counter[str] = Counter()
        for name in labels:
            for line in archive.read(name).decode("utf-8").splitlines():
                if line.strip():
                    class_id = int(line.split()[0])
                    per_class[
                        expected.class_names[class_id]
                        if 0 <= class_id < len(expected.class_names)
                        else f"id {class_id}"
                    ] += 1
        yaml_names = yaml.safe_load(archive.read("data.yaml").decode("utf-8")).get("names", {})
    digest = hashlib.sha256(data).hexdigest()
    split_counts = Counter(n.split("/")[1] for n in images)
    return ZipCheck(
        sha256=digest,
        matches_record=digest == expected.zip_sha256,
        images=len(images),
        label_files=len(labels),
        annotations=sum(per_class.values()),
        boxes_per_class=dict(sorted(per_class.items())),
        splits={s: split_counts[s] for s in SPLITS},
        data_yaml_names=[str(yaml_names[k]) for k in sorted(yaml_names)],
    )


# ----------------------------------------------------------------------------- checks


class Check(StrictModel):
    capability: str
    status: Status
    result: Result
    observed: str | None
    expected: str | None
    evidence: str


class Statement(StrictModel):
    capability: str
    status: Status
    note: str


class Generator(StrictModel):
    command: str
    code_commit: str | None
    code_dirty: bool | None


class SmokeRecord(StrictModel):
    schema_version: int = 1
    milestone: str = "M6"
    verdict: Literal["PASS", "FAIL"]
    verdict_rule: str
    observed_on: date
    observer: str
    platform: str
    dataset: ObservedDataset
    version: ObservedVersion
    dataset_health: DatasetHealth
    expected_package: str
    expected_zip_sha256: str
    checks: list[Check]
    statements: list[Statement]
    zip_check: ZipCheck | None
    inputs: dict[str, str]
    generated_by: Generator


VERDICT_RULE = (
    "PASS when every comparison between an EVREN observation and the committed expectation is a "
    "MATCH (format, import counts, class names and counts, split counts after import, the items "
    "opened one by one, the frozen version and its split), Auto Split was not used, and, when the "
    "ZIP was available locally, its SHA-256 and contents match the record made before the upload."
)


def _fmt(counts: Mapping[str, int]) -> str:
    return ", ".join(f"{k} {v}" for k, v in counts.items())


def _check(
    capability: str, observed: str, expected: str, evidence: str, *, status: Status
) -> Check:
    return Check(
        capability=capability,
        status=status,
        result="MATCH" if observed == expected else "MISMATCH",
        observed=observed,
        expected=expected,
        evidence=evidence,
    )


def build_checks(observed: Observation, expected: Expected) -> list[Check]:
    """Every observation compared with the committed expectation, in a fixed order."""
    e_splits = expected.splits
    checks = [
        _check(
            "YOLO Detection ZIP import",
            f"{observed.upload.format_detected}; import completed: {observed.upload.import_completed}",
            "YOLO Detection; import completed: True",
            f"package {observed.upload.package}; the committed format is {expected.format}",
            status="OBSERVED_IN_EVREN",
        ),
        _check(
            "import counts (images, annotations, classes, unlabelled images)",
            f"{observed.import_summary.images}, {observed.import_summary.annotations}, "
            f"{observed.import_summary.classes}, {observed.import_summary.unlabelled_images}",
            f"{len(expected.items)}, {expected.annotations}, {len(expected.class_names)}, "
            f"{sum(1 for i in expected.items if i.boxes == 0)}",
            "expected-splits.csv (one row per item, boxes per item) and smoke.json (classes)",
            status="OBSERVED_IN_EVREN",
        ),
        _check(
            "class names and box counts per class",
            _fmt(
                {
                    n: observed.classes_shown[n]
                    for n in expected.class_names
                    if n in observed.classes_shown
                }
                | {k: v for k, v in observed.classes_shown.items() if k not in expected.class_names}
            ),
            _fmt(expected.boxes_per_class),
            "annotations.parquet rows of the 20 smoke items",
            status="OBSERVED_IN_EVREN",
        ),
        _check(
            "supplied train/val/test split kept on import (aggregate counts)",
            _fmt({s: observed.splits_shown.get(s, 0) for s in SPLITS}),
            _fmt(e_splits),
            "split panel after the import, Auto Split not run; expected-splits.csv",
            status="OBSERVED_IN_EVREN",
        ),
    ]
    by_file = {i.file_name: i for i in expected.items}
    for item in observed.items_checked:
        twin = by_file.get(item.file_name)
        checks.append(
            _check(
                f"item {item.file_name}: split and labels",
                f"{item.split} ({item.split_ui}); {';'.join(sorted(item.labels_shown))}",
                "not in the package"
                if twin is None
                else f"{twin.split} ({observed.split_labels_ui.get(twin.split, twin.split)}); "
                + ";".join(sorted(twin.classes)),
                "the item opened in the UI; expected-splits.csv",
                status="OBSERVED_IN_EVREN",
            )
        )
    v = observed.version
    checks += [
        _check(
            "frozen dataset version keeps the counts",
            f"frozen: {v.frozen}; {v.summary.items} items, {v.summary.labelled} labelled, "
            f"{v.summary.annotations} annotations, {v.summary.classes} classes",
            f"frozen: True; {len(expected.items)} items, "
            f"{sum(1 for i in expected.items if i.boxes > 0)} labelled, {expected.annotations} "
            f"annotations, {len(expected.class_names)} classes",
            f"version {v.name}: {v.message_ui!r}",
            status="OBSERVED_IN_EVREN",
        ),
        _check(
            "frozen dataset version keeps the supplied split",
            _fmt({s: v.splits.get(s, 0) for s in SPLITS}),
            _fmt(e_splits),
            "version created with "
            + " and ".join(repr(o) for o in v.options_left_off)
            + " left off",
            status="OBSERVED_IN_EVREN",
        ),
        _check(
            "Auto Split not used",
            str(observed.upload.auto_split_used),
            "False",
            "the protocol of docs/EVREN.md: never re-split an imported dataset",
            status="OBSERVED_IN_EVREN",
        ),
    ]
    return checks


def zip_checks(found: ZipCheck, expected: Expected) -> list[Check]:
    return [
        _check(
            "local ZIP is the recorded package",
            found.sha256,
            expected.zip_sha256,
            "SHA-256 of the file in <OPENINSPECT_DATA_DIR>/exports/ against smoke.json",
            status="LOCALLY_VERIFIED",
        ),
        _check(
            "local ZIP contents (images, annotations, splits, class names)",
            f"{found.images}, {found.annotations}, {_fmt(found.splits)}, "
            + ";".join(found.data_yaml_names),
            f"{len(expected.items)}, {expected.annotations}, {_fmt(expected.splits)}, "
            + ";".join(expected.class_names),
            "members of the archive counted directly",
            status="LOCALLY_VERIFIED",
        ),
        _check(
            "local ZIP box counts per class",
            _fmt({n: found.boxes_per_class.get(n, 0) for n in expected.class_names}),
            _fmt(expected.boxes_per_class),
            "label lines of the archive",
            status="LOCALLY_VERIFIED",
        ),
    ]


def statements(observed: Observation, expected: Expected) -> list[Statement]:
    """What the smoke test does and does not establish, beyond the checks."""
    opened = len(observed.items_checked)
    aligned = sum(1 for i in observed.items_checked if i.boxes_visually_aligned)
    return [
        Statement(
            capability="bounding boxes drawn where the defects are",
            status="OBSERVED_IN_EVREN",
            note=f"judged visually by the maintainer on the {aligned} of {opened} items opened; not measured",
        ),
        Statement(
            capability="dataset version creation and freezing",
            status="OBSERVED_IN_EVREN",
            note=f"version {observed.version.name} created and frozen ({observed.version.message_ui!r})",
        ),
        Statement(
            capability="Dataset Health panel",
            status="OBSERVED_IN_EVREN",
            note=(
                f"grade {observed.dataset_health.grade}, score {observed.dataset_health.score}; an EVREN "
                "platform score, not an OpenInspect assurance result; data volume is low by design "
                f"({len(expected.items)} items)"
            ),
        ),
        Statement(
            capability="split of every one of the 20 items, item by item",
            status="NOT_TESTED",
            note=(
                f"aggregate counts matched and {opened} items (one per split) were opened; the other "
                f"{len(expected.items) - opened} were not checked individually and no machine-readable "
                "export or API listing was available"
            ),
        ),
        Statement(
            capability="file names, pixels and label files kept byte for byte",
            status="UNKNOWN",
            note="the opened items showed their global-id file names; no EVREN export was downloaded and hashed",
        ),
        Statement(
            capability="Auto Split and the version options that re-split",
            status="NOT_TESTED",
            note="deliberately left off",
        ),
        Statement(
            capability="import of the full release, other split schemes or COCO JSON",
            status="NOT_TESTED",
            note="only the 20-item YOLO Detection smoke package was imported",
        ),
        Statement(
            capability="training, evaluation and the inference API",
            status="NOT_TESTED",
            note="no training job was started (training_started: false); max_det and the confidence floor stay UNKNOWN",
        ),
        Statement(
            capability="dataset, version and training APIs",
            status="UNKNOWN",
            note="everything was done in the UI; no endpoint was used or seen",
        ),
    ]


def make_record(
    observed: Observation,
    expected: Expected,
    zip_found: ZipCheck | None,
    *,
    inputs: Mapping[str, str],
    generator: Generator,
) -> SmokeRecord:
    checks = build_checks(observed, expected)
    if zip_found is not None:
        checks += zip_checks(zip_found, expected)
    passed = all(c.result == "MATCH" for c in checks) and not observed.upload.auto_split_used
    return SmokeRecord(
        verdict="PASS" if passed else "FAIL",
        verdict_rule=VERDICT_RULE,
        observed_on=observed.observed_on,
        observer=observed.observer,
        platform=observed.platform,
        dataset=observed.dataset,
        version=observed.version,
        dataset_health=observed.dataset_health,
        expected_package=expected.package,
        expected_zip_sha256=expected.zip_sha256,
        checks=checks,
        statements=statements(observed, expected),
        zip_check=zip_found,
        inputs=dict(sorted(inputs.items())),
        generated_by=generator,
    )


# ------------------------------------------------------------------------------ report


def _cell(value: str | None) -> str:
    return "—" if value is None else value.replace("|", "\\|")


def render(record: SmokeRecord, smoke_dir: str) -> str:
    lines = [
        "# M6: EVREN import smoke test",
        "",
        f"Generated by `{record.generated_by.command}` from `{smoke_dir}/observed.yaml`, the package's "
        "committed expectation and, when available, the ZIP "
        f"(code `{(record.generated_by.code_commit or 'unknown')[:12]}`). The observations were made "
        f"by the {record.observer} in the {record.platform} on {record.observed_on.isoformat()} and "
        "transcribed as text; no screenshot is committed.",
        "",
        f"## Verdict: **{record.verdict}**",
        "",
        record.verdict_rule,
        "",
        f"Dataset `{record.dataset.name}` ({record.dataset.visibility}, licence {record.dataset.licence}, "
        f"tags {', '.join(record.dataset.tags)}); package `{record.expected_package}`, SHA-256 "
        f"`{record.expected_zip_sha256}` recorded before the upload.",
        "",
        "## Observations against the committed expectation",
        "",
        "| capability | status | result | observed | expected | evidence |",
        "|---|---|---|---|---|---|",
    ]
    for c in record.checks:
        lines.append(
            f"| {c.capability} | {c.status} | **{c.result}** | {_cell(c.observed)} | "
            f"{_cell(c.expected)} | {_cell(c.evidence)} |"
        )
    lines += [
        "",
        "## What the test establishes, and what it does not",
        "",
        "| capability | status | note |",
        "|---|---|---|",
    ]
    for s in record.statements:
        lines.append(f"| {s.capability} | {s.status} | {_cell(s.note)} |")
    health = record.dataset_health
    lines += [
        "",
        "## EVREN's Dataset Health panel",
        "",
        f"Grade **{health.grade}**, score {health.score} ({health.label_ui!r}); subscores "
        + ", ".join(
            f"{k.replace('_', ' ')} {health.subscores[k]}%"
            for k in [
                *(k for k in SUBSCORES if k in health.subscores),
                *sorted(set(health.subscores) - set(SUBSCORES)),
            ]
        )
        + f". Warning shown: {health.warning}.",
        "",
        "This is EVREN's platform health score of a 20-image smoke dataset. It is not an "
        "OpenInspect-Trust assurance result and says nothing about leakage, provenance or label "
        "quality; the two must not be mixed.",
        "",
        "## Reading",
        "",
        "- For this YOLO Detection package, EVREN was **observed to preserve the supplied split "
        "assignment**: the aggregate counts after import (10 / 5 / 5) match, and one known item "
        "per split showed its expected split and labels. This does not verify all 20 items one "
        "by one, and it says nothing about other layouts or larger imports.",
        "- The dataset version was created and frozen with the re-split options off, and the "
        "frozen version kept the 10 / 5 / 5 split.",
        "- The local manifest stays the canonical split: every later import is re-checked against "
        "its split file before training.",
        "",
        "## Inputs",
        "",
        "| file | SHA-256 |",
        "|---|---|",
        *(f"| `{name}` | `{digest}` |" for name, digest in record.inputs.items()),
        "",
    ]
    return "\n".join(lines)
