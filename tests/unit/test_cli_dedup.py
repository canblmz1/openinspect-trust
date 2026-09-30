"""``openinspect dedup``: the whole audit on small synthetic images with a stub embedder."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from PIL import ImageEnhance

from openinspect.dedup.embedder import EmbedderSpec
from openinspect.dedup.perf import read_runs
from openinspect.dedup.tables import AUDIT, GROUPS, NEIGHBOURS, PAIRS, REVIEW, read_audit
from tests.conftest import Repo
from tests.dedup_helpers import (
    Spec,
    StubEmbedder,
    make_image,
    make_spec,
    write_items,
    write_records,
)
from tests.factories import accepted_manifest

SOURCES = ("dspcbsd-plus", "pcb-defect", "pcb-ind")
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
    weights_sha256: "0000000000000000000000000000000000000000000000000000000000000000"
    dim: 24
    licence: Apache-2.0
"""


def variants(seed: int, count: int) -> list[Any]:
    base = make_image(seed, size=(64, 48))
    return [ImageEnhance.Brightness(base).enhance(1.0 + 0.02 * m) for m in range(count)]


def build_data(data: Path) -> None:
    dsp: list[Spec] = []
    for c in range(4):
        for m, image in enumerate(variants(100 + c, 3)):
            dsp.append(Spec(f"S_{c}_{m}.jpg", image, "val" if (c < 2 and m == 2) else "train"))
    for k in range(4):
        dsp.append(Spec(f"S_x{k}.jpg", make_image(200 + k, size=(64, 48)), "train"))
    ind: list[Spec] = []
    splits = ["train", "train", "val", "test", "train", "train"]
    for batch in range(6):
        for s, side in enumerate(("b", "t")):
            for m, image in enumerate(variants(300 + 2 * batch + s, 5)):
                ind.append(
                    Spec(
                        f"{batch:04d}_{side}_{m:03d}.jpg",
                        image,
                        splits[batch],
                        f"{batch:04d}",
                        f"{batch:04d}_{side}",
                    )
                )
    defect: list[Spec] = []
    for family in range(3):
        for b in range(2):
            for m, image in enumerate(variants(500 + 2 * family + b, 4)):
                defect.append(
                    Spec(
                        f"{family + 1:02d}-{b + 1}-{m:02d}.png",
                        image,
                        None,
                        f"{family + 1:02d}",
                        f"{family + 1:02d}-{b + 1}",
                    )
                )
    for source, specs in zip(SOURCES, (dsp, defect, ind), strict=True):
        write_records(data, source, write_items(data, source, specs))


class Setup:
    def __init__(self, repo: Repo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.repo = repo
        self.tmp = tmp_path
        self.data = tmp_path / "data"
        for slug in SOURCES:
            repo.write_manifest(accepted_manifest(slug))
        (repo.root / "configs" / "dedup.yaml").write_text(CONFIG, encoding="utf-8")
        build_data(self.data)
        self.stubs: list[StubEmbedder] = []

        def load(spec: EmbedderSpec, root: Path, data: Path, threads: int | None) -> StubEmbedder:
            stub = StubEmbedder(spec)
            self.stubs.append(stub)
            return stub

        monkeypatch.setattr("openinspect.cli.dedup.load_embedder_for", load)

    def cli(self, *args: str, data: bool = True) -> Any:
        extra = ["--data-dir", str(self.data)] if data else []
        return self.repo.cli("dedup", *args, *extra)

    @property
    def embedded(self) -> int:
        return sum(stub.images for stub in self.stubs)


@pytest.fixture
def setup(repo: Repo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Setup:
    return Setup(repo, tmp_path, monkeypatch)


def test_the_audit_runs_stage_by_stage(setup: Setup) -> None:
    first = setup.cli("features", "--all")
    assert first.exit_code == 0, first.output
    assert "100 images (100 distinct): 0 from cache, 100 embedded, 0 failed" in first.output
    again = setup.cli("features", "--all")
    assert again.exit_code == 0, again.output
    assert "100 from cache, 0 embedded" in again.output
    assert setup.embedded == 100
    assert [r["embedded"] for r in read_runs(setup.data, "features")] == [100, 0]

    missing = setup.cli("analyze", "--all", "--per-source", "3")
    assert missing.exit_code == 1
    assert "run `openinspect dedup synthetic`" in missing.output

    synthetic = setup.cli("synthetic", "--all", "--per-source", "3")
    assert synthetic.exit_code == 0, synthetic.output
    assert "99 synthetic pairs from 9 images: 99 copies embedded, 0 from cache" in synthetic.output

    out, reports = setup.tmp / "artifacts", setup.tmp / "reports"
    analyzed = setup.cli(
        "analyze", "--all", "--per-source", "3", "--out", str(out), "--reports", str(reports)
    )
    assert analyzed.exit_code == 0, analyzed.output
    assert "thresholds: review" in analyzed.output
    for name in (PAIRS, NEIGHBOURS, GROUPS, REVIEW, AUDIT):
        assert (out / name).is_file(), name
    audit = read_audit(out / AUDIT)
    assert audit.run.images == 100
    assert audit.run.code_commit is None  # the throw-away repository is not a git repository
    assert set(audit.artifacts) == {PAIRS, NEIGHBOURS, GROUPS, REVIEW}
    assert audit.performance is not None
    stages = [s.stage for s in audit.performance.stages]
    assert stages[:2] == ["embeddings (cache build)", "synthetic copies"]
    assert "calibration" in stages
    rendered = {
        p.relative_to(reports).as_posix(): p.read_bytes() for p in reports.rglob("*") if p.is_file()
    }
    assert "split-leakage.md" in rendered

    again_reports = setup.tmp / "reports-again"
    report = setup.cli("report", "--out", str(out), "--reports", str(again_reports), data=False)
    assert report.exit_code == 0, report.output
    rerendered = {
        p.relative_to(again_reports).as_posix(): p.read_bytes()
        for p in again_reports.rglob("*")
        if p.is_file()
    }
    assert rerendered == rendered

    pack = setup.tmp / "pack"
    review = setup.cli("review", "--all", "--out", str(out), "--target", str(pack))
    assert review.exit_code == 0, review.output
    html = (pack / "review-pack.html").read_text(encoding="utf-8")
    assert "data:image/jpeg;base64," in html
    assert "Seeded sample of similarity groups" in html
    assert "sampled groups" in review.output


def test_run_does_every_stage_and_reuses_the_caches(setup: Setup) -> None:
    out, reports = setup.tmp / "artifacts", setup.tmp / "reports"
    args = ["run", "--all", "--per-source", "2", "--out", str(out), "--reports", str(reports)]
    first = setup.cli(*args)
    assert first.exit_code == 0, first.output
    assert (setup.data / "m3" / "review" / "review-pack.html").is_file()
    embedded = setup.embedded
    second = setup.cli(*args)
    assert second.exit_code == 0, second.output
    assert setup.embedded == embedded  # nothing is embedded twice
    audit = json.loads((out / AUDIT).read_text(encoding="utf-8"))
    assert audit["synthetic"]["sample_per_source"] == 2


def test_a_sample_embeds_only_part_of_each_source(setup: Setup) -> None:
    result = setup.cli("features", "--all", "--sample", "2")
    assert result.exit_code == 0, result.output
    assert "6 images (6 distinct)" in result.output
    assert setup.embedded == 6


def test_commands_fail_cleanly(setup: Setup) -> None:
    unknown = setup.cli("features", "--all", "--model", "missing")
    assert unknown.exit_code == 1
    assert "unknown model" in unknown.output
    no_features = setup.cli("analyze", "--all")
    assert no_features.exit_code == 1
    assert "no embedding in the cache" in no_features.output
    no_audit = setup.cli("report", "--out", str(setup.tmp / "nothing"), data=False)
    assert no_audit.exit_code == 1
    assert "cannot read audit.json" in no_audit.output
    no_review = setup.cli("review", "--all", "--out", str(setup.tmp / "nothing"))
    assert no_review.exit_code == 1
    missing_source = setup.cli("features")
    assert missing_source.exit_code == 1
    assert "name at least one source" in missing_source.output


def test_missing_records_are_reported(setup: Setup) -> None:
    for path in (setup.data / "records" / "pcb-ind").iterdir():
        path.unlink()
    result = setup.cli("synthetic", "pcb-ind")
    assert result.exit_code == 1
    assert "no image records" in result.output


def test_an_unreadable_image_stops_the_synthetic_stage_with_a_message(setup: Setup) -> None:
    assert setup.cli("features", "pcb-defect").exit_code == 0
    first = sorted((setup.data / "extracted" / "pcb-defect").glob("*.png"))[0]
    first.write_bytes(b"changed on disk")
    result = setup.cli("synthetic", "pcb-defect", "--per-source", "30")
    assert result.exit_code == 1
    assert "differs from the recorded" in result.output


def test_an_embedder_for_another_model_is_refused(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = make_spec(name="other", dim=24)
    monkeypatch.setattr("openinspect.cli.dedup.load_embedder_for", lambda *_: StubEmbedder(other))
    result = setup.cli("features", "pcb-defect")
    assert result.exit_code == 1
    assert "does not match" in result.output
