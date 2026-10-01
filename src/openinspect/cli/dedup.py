"""``openinspect dedup features | synthetic | analyze | review | report | run`` (Milestone 3).

The audit detects, groups, measures and reports; it never deletes, excludes or re-labels an image.
Heavy inputs (embedding cache, synthetic copies, the HTML review pack) stay in the data directory;
the repository receives the small artifacts (``artifacts/m3``) and the reports (``reports/m3``).
"""

from __future__ import annotations

import os
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer

from openinspect.assurance import collect_provenance
from openinspect.cli.common import (
    AllOption,
    DataDirOption,
    RepoRootOption,
    SlugsArgument,
    fail,
    log,
    select_sources,
    setup,
)
from openinspect.dedup.analysis import (
    AnalysisError,
    AnalysisResult,
    Settings,
    robustness,
    run_analysis,
    settings_from_config,
)
from openinspect.dedup.cache import EmbeddingCache
from openinspect.dedup.compute import ComputeError, FeatureSet, HashStore, compute_features
from openinspect.dedup.config import ConfigError, DedupConfig, ModelEntry, load_config
from openinspect.dedup.embedder import (
    Embedder,
    EmbedderError,
    EmbedderSpec,
    load_dinov2,
    spec_from_config,
)
from openinspect.dedup.features import DecodeError
from openinspect.dedup.graph import GraphError
from openinspect.dedup.hashing import PHASH_VERSION
from openinspect.dedup.inventory import ImageItem, InventoryError, Unreadable, load_items
from openinspect.dedup.perf import (
    RunRecord,
    StageTiming,
    append_run,
    build_performance,
    code_version,
    cpu_name,
    read_runs,
    timed,
)
from openinspect.dedup.report import write_reports
from openinspect.dedup.review import ReviewError, sample_groups, write_review_pack
from openinspect.dedup.synthetic import (
    SyntheticError,
    SyntheticPair,
    compute_synthetic,
    read_pairs,
    sample_for_synthetic,
    write_pairs,
)
from openinspect.dedup.tables import (
    AUDIT,
    GROUPS,
    REVIEW,
    read_audit,
    read_groups,
    read_review,
    write_artifacts,
    write_audit,
)
from openinspect.dedup.thresholds import CalibrationError
from openinspect.dedup.transforms import TRANSFORMS
from openinspect.validation import QueueError, queue_label, read_queue

dedup_app = typer.Typer(
    help="Duplicate and leakage audit: hashes, embeddings, similarity groups, review packs.",
    no_args_is_help=True,
)

SYNTHETIC_PER_SOURCE = 100  # docs/M3_PROTOCOL.md section 5
ARTIFACTS = Path("artifacts") / "m3"
REPORTS = Path("reports") / "m3"

ModelOption = Annotated[
    str | None,
    typer.Option("--model", help="Model key in configs/dedup.yaml (default: its default)."),
]
SampleOption = Annotated[
    int | None,
    typer.Option(
        "--sample", min=1, help="Seeded random sample of N images per source (smoke runs)."
    ),
]
SeedOption = Annotated[int, typer.Option("--seed", help="Seed of every sampled step.")]
PerSourceOption = Annotated[
    int, typer.Option("--per-source", min=1, help="Images per source for the synthetic copies.")
]
BatchOption = Annotated[int, typer.Option("--batch-size", min=1)]
ThreadsOption = Annotated[int | None, typer.Option("--threads", min=1, help="Torch threads.")]
OutOption = Annotated[
    Path | None,
    typer.Option("--out", file_okay=False, help="Artifact folder (default: artifacts/m3)."),
]
ReportsOption = Annotated[
    Path | None,
    typer.Option("--reports", file_okay=False, help="Report folder (default: reports/m3)."),
]
RobustnessOption = Annotated[
    str | None,
    typer.Option(
        "--robustness-model",
        help="Second model for the representation check (its features and synthetic copies "
        "must be cached: run features and synthetic with --model first).",
    ),
]


def load_embedder_for(  # pragma: no cover - needs torch and the pinned weights
    spec: EmbedderSpec, root: Path, data: Path, threads: int | None
) -> Embedder:
    """The embedding model of ``spec`` (hook for tests: they replace this with a stub)."""
    config = load_config(root)
    _, entry = config.model(spec.name)
    return load_dinov2(spec, entry, data_dir=data, threads=threads)


def originals_cache(data: Path, spec: EmbedderSpec) -> EmbeddingCache:
    return EmbeddingCache(
        data,
        model_key=spec.model_key,
        preprocessing_version=spec.preprocessing_version,
        backend=spec.backend,
        dim=spec.dim,
    )


def synthetic_cache(data: Path, spec: EmbedderSpec) -> EmbeddingCache:
    return EmbeddingCache(
        data / "m3" / "synthetic",
        model_key=spec.model_key,
        preprocessing_version=spec.preprocessing_version,
        backend=spec.backend,
        dim=spec.dim,
    )


def synthetic_path(data: Path, spec: EmbedderSpec, seed: int, per_source: int) -> Path:
    """The synthetic pairs of one model, preprocessing, backend, seed and sample size."""
    return synthetic_cache(data, spec).directory / f"pairs-seed{seed}-n{per_source}.jsonl"


def hash_store(data: Path) -> HashStore:
    return HashStore(data / "m3" / "hashes" / f"{PHASH_VERSION}.jsonl")


def sample_items(items: list[ImageItem], per_source: int | None, seed: int) -> list[ImageItem]:
    """All items, or a seeded random sample of ``per_source`` images of each source (order kept)."""
    if per_source is None:
        return items
    chosen: list[ImageItem] = []
    for source in sorted({item.source for item in items}):
        pool = [item for item in items if item.source == source]
        if len(pool) > per_source:
            rng = random.Random(f"{seed}:{source}")  # noqa: S311 - reproducible sampling, not cryptography
            picks = sorted(rng.sample(range(len(pool)), per_source))
            pool = [pool[i] for i in picks]
        chosen.extend(pool)
    return chosen


@dataclass(frozen=True)
class Context:
    root: Path
    data: Path
    config: DedupConfig
    spec: EmbedderSpec
    entry: ModelEntry
    items: list[ImageItem]
    skipped: list[Unreadable]


def context(
    repo_root: Path | None,
    data_dir: Path | None,
    slugs: list[str] | None,
    all_sources: bool,
    model: str | None,
) -> Context:
    root, data, registry = setup(repo_root, data_dir)
    selected = select_sources(registry, slugs, all_sources)
    try:
        config = load_config(root)
        _, entry = config.model(model)
        spec = spec_from_config(config, model)
        acquisition = {slug: source.acquisition_id for slug, source in config.sources.items()}
        items, skipped = load_items(
            data, [lm.manifest.slug for lm in selected], acquisition=acquisition
        )
    except (ConfigError, InventoryError) as exc:
        fail(str(exc))
    return Context(root, data, config, spec, entry, items, skipped)


def run_features(
    ctx: Context,
    *,
    batch_size: int,
    threads: int | None,
    workers: int,
    sample: int | None,
    seed: int,
) -> FeatureSet:
    items = sample_items(ctx.items, sample, seed)
    timings: list[StageTiming] = []
    log(
        f"{len(items):,} images, model {ctx.spec.name} ({ctx.spec.model_key}), backend {ctx.spec.backend}"
    )
    try:
        with timed("features", timings):
            result = compute_features(
                items,
                spec=ctx.spec,
                cache=originals_cache(ctx.data, ctx.spec),
                hashes=hash_store(ctx.data),
                make_embedder=lambda: load_embedder_for(
                    ctx.spec, ctx.root, ctx.data, threads or os.cpu_count()
                ),
                batch_size=batch_size,
                workers=workers,
                progress=log,
            )
    except (ComputeError, EmbedderError) as exc:
        fail(str(exc))
    stats = result.stats
    if stats is None:  # pragma: no cover - compute_features always returns stats
        fail("no statistics")
    peak = timings[-1].peak_ram_bytes
    append_run(
        ctx.data,
        "features",
        {
            "model_key": ctx.spec.model_key,
            "items": stats.items,
            "unique": stats.unique_images,
            "cache_hits": stats.cache_hits,
            "embedded": stats.embedded,
            "failed": stats.failed,
            "wall_seconds": round(stats.wall_seconds, 3),
            "embed_seconds": round(stats.embed_seconds, 3),
            "images_per_second": stats.images_per_second,
            "model_images_per_second": stats.model_images_per_second,
            "cache_files": stats.cache_files,
            "cache_bytes": stats.cache_bytes,
            "peak_ram_bytes": peak,
            "batch_size": batch_size,
            "threads": threads,
            "workers": workers,
            "cpu": cpu_name(),
        },
    )
    typer.echo(
        f"{stats.items:,} images ({stats.unique_images:,} distinct): {stats.cache_hits:,} from cache, "
        f"{stats.embedded:,} embedded, {stats.failed} failed, {len(ctx.skipped)} undecodable at ingest"
    )
    if stats.images_per_second is not None:
        typer.echo(
            f"throughput {stats.images_per_second:.1f} images/s overall, "
            f"{stats.model_images_per_second or 0:.1f} images/s in the model; "
            f"wall {stats.wall_seconds:.0f} s"
        )
    typer.echo(f"cache: {stats.cache_files:,} files, {stats.cache_bytes / 1e6:.1f} MB")
    if peak is not None:
        typer.echo(f"peak RAM {peak / 1e9:.2f} GB")
    for failure in result.failures:
        typer.echo(
            f"FAILED {failure.source}:{failure.item_id} [{failure.stage}] {failure.error}", err=True
        )
    return result


def run_synthetic(
    ctx: Context, *, per_source: int, seed: int, batch_size: int, threads: int | None
) -> list[SyntheticPair]:
    sample = sample_for_synthetic(ctx.items, per_source, seed)
    cache = synthetic_cache(ctx.data, ctx.spec)
    before, _ = cache.stats()
    timings: list[StageTiming] = []
    log(f"{len(sample):,} images x {len(TRANSFORMS)} transforms, model {ctx.spec.name}")
    try:
        with timed("synthetic", timings):
            pairs = compute_synthetic(
                sample,
                originals=originals_cache(ctx.data, ctx.spec),
                cache=cache,
                spec=ctx.spec,
                make_embedder=lambda: load_embedder_for(
                    ctx.spec, ctx.root, ctx.data, threads or os.cpu_count()
                ),
                seed=seed,
                batch_size=batch_size,
                progress=log,
            )
    except (SyntheticError, EmbedderError, DecodeError) as exc:
        fail(str(exc))
    target = synthetic_path(ctx.data, ctx.spec, seed, per_source)
    write_pairs(target, pairs)
    after, size = cache.stats()
    timing = timings[-1]
    append_run(
        ctx.data,
        "synthetic",
        {
            "model_key": ctx.spec.model_key,
            "images": len(sample),
            "pairs": len(pairs),
            "embedded": after - before,
            "wall_seconds": round(timing.seconds, 3),
            "peak_ram_bytes": timing.peak_ram_bytes,
            "cache_files": after,
            "cache_bytes": size,
            "seed": seed,
            "cpu": cpu_name(),
        },
    )
    typer.echo(
        f"{len(pairs):,} synthetic pairs from {len(sample):,} images: "
        f"{after - before:,} copies embedded, {len(pairs) - (after - before):,} from cache; "
        f"{timing.seconds:.0f} s"
    )
    typer.echo(f"cache: {after:,} files, {size / 1e6:.1f} MB; pairs: {target.name}")
    if timing.peak_ram_bytes is not None:
        typer.echo(f"peak RAM {timing.peak_ram_bytes / 1e9:.2f} GB")
    return pairs


def analyse_model(
    ctx: Context,
    spec: EmbedderSpec,
    weights_sha256: str,
    *,
    seed: int,
    per_source: int,
    timings: list[StageTiming] | None,
) -> tuple[FeatureSet, AnalysisResult]:
    """Features of ``spec`` from its caches (no model), its synthetic pairs, and the whole audit."""
    stages = timings if timings is not None else []
    with timed("load features", stages):
        features = compute_features(
            ctx.items,
            spec=spec,
            cache=originals_cache(ctx.data, spec),
            hashes=hash_store(ctx.data),
            make_embedder=None,
        )
    synthetic = read_pairs(synthetic_path(ctx.data, spec, seed, per_source))
    log(f"{spec.name}: {len(features.items):,} images, {len(synthetic):,} synthetic pairs")
    result = run_analysis(
        features,
        synthetic,
        spec=spec,
        weights_sha256=weights_sha256,
        skipped=ctx.skipped,
        settings=settings_from_config(ctx.config, Settings(seed=seed)),
        timings=timings,
    )
    return features, result


def _other_runs(
    ctx: Context, model: str | None
) -> list[tuple[str, list[RunRecord], list[RunRecord]]]:
    """The recorded embedding runs of the robustness model, for the performance report."""
    if model is None:
        return []
    key = spec_from_config(ctx.config, model).model_key
    return [
        (
            model,
            [r for r in read_runs(ctx.data, "features") if r.get("model_key") == key],
            [r for r in read_runs(ctx.data, "synthetic") if r.get("model_key") == key],
        )
    ]


def run_analyze(
    ctx: Context,
    *,
    seed: int,
    per_source: int,
    out: Path,
    reports: Path,
    robustness_model: str | None = None,
) -> None:
    commit, dirty = code_version(ctx.root)  # the code of this process was loaded at its start
    timings: list[StageTiming] = []
    try:
        features, result = analyse_model(
            ctx,
            ctx.spec,
            ctx.entry.weights_sha256,
            seed=seed,
            per_source=per_source,
            timings=timings,
        )
        check = None
        if robustness_model is not None:
            with timed(f"robustness ({robustness_model})", timings):
                other_name, other_entry = ctx.config.model(robustness_model)
                other_spec = spec_from_config(ctx.config, other_name)
                _, other = analyse_model(
                    ctx,
                    other_spec,
                    other_entry.weights_sha256,
                    seed=seed,
                    per_source=per_source,
                    timings=None,
                )
                check = robustness(
                    result, other, other_model=f"{other_spec.model_id}@{other_spec.revision[:12]}"
                )
        with timed("artifacts", timings):
            digests = write_artifacts(out, features, result)
        slugs = sorted({item.source for item in ctx.items})
        acquisition = {slug: entry.acquisition_id for slug, entry in ctx.config.sources.items()}
        provenance = collect_provenance(ctx.root, slugs, acquisition)
    except (
        ComputeError,
        SyntheticError,
        AnalysisError,
        CalibrationError,
        GraphError,
        ConfigError,
    ) as exc:
        fail(str(exc))
    cache_files, cache_bytes = originals_cache(ctx.data, ctx.spec).stats()
    performance = build_performance(
        timings,
        features_runs=[
            r for r in read_runs(ctx.data, "features") if r.get("model_key") == ctx.spec.model_key
        ],
        synthetic_runs=[
            r for r in read_runs(ctx.data, "synthetic") if r.get("model_key") == ctx.spec.model_key
        ],
        cache_files=cache_files,
        cache_bytes=cache_bytes,
        dim=ctx.spec.dim,
        others=_other_runs(ctx, robustness_model),
    )
    audit = result.audit.model_copy(
        update={
            "run": result.audit.run.model_copy(
                update={"code_commit": commit, "code_dirty": dirty, "seed": seed}
            ),
            "performance": performance,
            "artifacts": digests,
            "robustness": check,
            "provenance": provenance,
        }
    )
    write_audit(out / AUDIT, audit)
    try:
        validation = read_queue(out / REVIEW, queue_label(out / REVIEW, ctx.root))
    except QueueError as exc:
        fail(str(exc))
    written = write_reports(reports, audit, validation)
    thresholds = audit.thresholds
    typer.echo(
        f"thresholds: review {thresholds.review}, family {thresholds.family}, near {thresholds.near}, "
        f"pHash <= {thresholds.phash_candidate}"
    )
    for note in result.notes:
        typer.echo(f"note: {note}")
    for name in sorted(digests):
        typer.echo(f"{name}: {(out / name).stat().st_size / 1e6:.2f} MB")
    typer.echo(f"reports: {len(written)} files in {reports.as_posix()}")


GROUPS_PER_SOURCE = 10  # seeded sample of family-level groups for the qualitative look (section 9f)


def run_review(ctx: Context, *, artifacts: Path, target: Path, seed: int = 0) -> Path:
    try:
        rows = read_review(artifacts / REVIEW)
        audit = read_audit(artifacts / AUDIT)
        groups = sample_groups(
            read_groups(artifacts / GROUPS), per_source=GROUPS_PER_SOURCE, seed=seed
        )
        path = write_review_pack(rows, ctx.items, target, audit=audit, groups=groups)
    except (OSError, ValueError, ReviewError) as exc:
        fail(str(exc))
    typer.echo(
        f"review pack: {len(rows):,} pairs and {len(groups):,} sampled groups in {path.as_posix()}"
    )
    return path


@dedup_app.command("features")
def features_command(
    slugs: SlugsArgument = None,
    all_sources: AllOption = False,
    model: ModelOption = None,
    sample: SampleOption = None,
    seed: SeedOption = 0,
    batch_size: BatchOption = 32,
    threads: ThreadsOption = None,
    workers: Annotated[int, typer.Option("--workers", min=1, help="Decoder threads.")] = 2,
    data_dir: DataDirOption = None,
    repo_root: RepoRootOption = None,
) -> None:
    """Decode every image once; compute perceptual hashes and embeddings; cache both."""
    ctx = context(repo_root, data_dir, slugs, all_sources, model)
    run_features(
        ctx, batch_size=batch_size, threads=threads, workers=workers, sample=sample, seed=seed
    )


@dedup_app.command("synthetic")
def synthetic_command(
    slugs: SlugsArgument = None,
    all_sources: AllOption = False,
    model: ModelOption = None,
    per_source: PerSourceOption = SYNTHETIC_PER_SOURCE,
    seed: SeedOption = 0,
    batch_size: BatchOption = 32,
    threads: ThreadsOption = None,
    data_dir: DataDirOption = None,
    repo_root: RepoRootOption = None,
) -> None:
    """Embed seeded, mildly transformed copies of a sample of images (synthetic positives)."""
    ctx = context(repo_root, data_dir, slugs, all_sources, model)
    run_synthetic(ctx, per_source=per_source, seed=seed, batch_size=batch_size, threads=threads)


@dedup_app.command("analyze")
def analyze_command(
    slugs: SlugsArgument = None,
    all_sources: AllOption = False,
    model: ModelOption = None,
    per_source: PerSourceOption = SYNTHETIC_PER_SOURCE,
    seed: SeedOption = 0,
    out: OutOption = None,
    reports: ReportsOption = None,
    robustness_model: RobustnessOption = None,
    data_dir: DataDirOption = None,
    repo_root: RepoRootOption = None,
) -> None:
    """Thresholds, similarity groups, split leakage, review queue; artifacts and reports (no model needed)."""
    ctx = context(repo_root, data_dir, slugs, all_sources, model)
    run_analyze(
        ctx,
        seed=seed,
        per_source=per_source,
        out=out or ctx.root / ARTIFACTS,
        reports=reports or ctx.root / REPORTS,
        robustness_model=robustness_model,
    )


@dedup_app.command("review")
def review_command(
    slugs: SlugsArgument = None,
    all_sources: AllOption = False,
    out: OutOption = None,
    target: Annotated[
        Path | None,
        typer.Option(
            "--target",
            file_okay=False,
            help="Where the HTML pack goes (default: <data>/m3/review).",
        ),
    ] = None,
    data_dir: DataDirOption = None,
    repo_root: RepoRootOption = None,
) -> None:
    """A local HTML contact sheet of the review queue (images stay outside the repository)."""
    ctx = context(repo_root, data_dir, slugs, all_sources, None)
    run_review(
        ctx, artifacts=out or ctx.root / ARTIFACTS, target=target or ctx.data / "m3" / "review"
    )


@dedup_app.command("report")
def report_command(
    out: OutOption = None,
    reports: ReportsOption = None,
    repo_root: RepoRootOption = None,
) -> None:
    """Re-render the reports from artifacts/m3/audit.json (no data directory needed)."""
    from openinspect.provenance.registry import find_repo_root

    root = repo_root.resolve() if repo_root is not None else find_repo_root()
    folder = out or root / ARTIFACTS
    source = folder / AUDIT
    try:
        audit = read_audit(source)
    except (OSError, ValueError) as exc:
        fail(f"cannot read {source.name}: {exc}")
    try:
        validation = read_queue(folder / REVIEW, queue_label(folder / REVIEW, root))
    except QueueError as exc:
        fail(str(exc))
    written = write_reports(reports or root / REPORTS, audit, validation)
    typer.echo(f"reports: {len(written)} files")


@dedup_app.command("run")
def run_command(
    slugs: SlugsArgument = None,
    all_sources: AllOption = False,
    model: ModelOption = None,
    per_source: PerSourceOption = SYNTHETIC_PER_SOURCE,
    seed: SeedOption = 0,
    batch_size: BatchOption = 32,
    threads: ThreadsOption = None,
    workers: Annotated[int, typer.Option("--workers", min=1, help="Decoder threads.")] = 2,
    out: OutOption = None,
    reports: ReportsOption = None,
    robustness_model: RobustnessOption = None,
    data_dir: DataDirOption = None,
    repo_root: RepoRootOption = None,
) -> None:
    """features, synthetic, analyze and review in one go; cached work is not repeated."""
    ctx = context(repo_root, data_dir, slugs, all_sources, model)
    artifacts = out or ctx.root / ARTIFACTS
    run_features(
        ctx, batch_size=batch_size, threads=threads, workers=workers, sample=None, seed=seed
    )
    run_synthetic(ctx, per_source=per_source, seed=seed, batch_size=batch_size, threads=threads)
    run_analyze(
        ctx,
        seed=seed,
        per_source=per_source,
        out=artifacts,
        reports=reports or ctx.root / REPORTS,
        robustness_model=robustness_model,
    )
    run_review(ctx, artifacts=artifacts, target=ctx.data / "m3" / "review")
