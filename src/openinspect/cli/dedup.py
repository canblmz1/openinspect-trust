"""``openinspect dedup features | ...``: the duplicate and leakage audit (Milestone 3)."""

from __future__ import annotations

import os
import random
from pathlib import Path
from typing import Annotated

import typer

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
from openinspect.dedup.cache import EmbeddingCache
from openinspect.dedup.compute import ComputeError, HashStore, compute_features
from openinspect.dedup.config import ConfigError, load_config
from openinspect.dedup.embedder import (
    Embedder,
    EmbedderError,
    EmbedderSpec,
    load_dinov2,
    spec_from_config,
)
from openinspect.dedup.hashing import PHASH_VERSION
from openinspect.dedup.inventory import ImageItem, InventoryError, load_items
from openinspect.dedup.perf import StageTiming, timed

dedup_app = typer.Typer(
    help="Duplicate and leakage audit: hashes, embeddings, similarity groups, review packs.",
    no_args_is_help=True,
)

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


def load_embedder_for(spec: EmbedderSpec, root: Path, data: Path, threads: int | None) -> Embedder:
    """The embedding model of ``spec`` (hook for tests: they replace this with a stub)."""
    config = load_config(root)
    _, entry = config.model(spec.name)
    return load_dinov2(spec, entry, data_dir=data, threads=threads)  # pragma: no cover


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


@dedup_app.command("features")
def features_command(
    slugs: SlugsArgument = None,
    all_sources: AllOption = False,
    model: ModelOption = None,
    sample: SampleOption = None,
    seed: Annotated[int, typer.Option("--seed", help="Seed of --sample.")] = 0,
    batch_size: Annotated[int, typer.Option("--batch-size", min=1)] = 32,
    threads: Annotated[int | None, typer.Option("--threads", min=1, help="Torch threads.")] = None,
    workers: Annotated[int, typer.Option("--workers", min=1, help="Decoder threads.")] = 2,
    data_dir: DataDirOption = None,
    repo_root: RepoRootOption = None,
) -> None:
    """Decode every image once; compute perceptual hashes and embeddings; cache both."""
    root, data, registry = setup(repo_root, data_dir)
    selected = select_sources(registry, slugs, all_sources)
    try:
        spec = spec_from_config(load_config(root), model)
        items, skipped = load_items(data, [lm.manifest.slug for lm in selected])
    except (ConfigError, InventoryError) as exc:
        fail(str(exc))
    items = sample_items(items, sample, seed)
    cache = EmbeddingCache(
        data,
        model_key=spec.model_key,
        preprocessing_version=spec.preprocessing_version,
        backend=spec.backend,
        dim=spec.dim,
    )
    hashes = HashStore(data / "m3" / "hashes" / f"{PHASH_VERSION}.jsonl")
    timings: list[StageTiming] = []
    log(f"{len(items):,} images, model {spec.name} ({spec.model_key}), backend {spec.backend}")
    try:
        with timed("features", timings):
            result = compute_features(
                items,
                spec=spec,
                cache=cache,
                hashes=hashes,
                make_embedder=lambda: load_embedder_for(
                    spec, root, data, threads or os.cpu_count()
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
    rate = stats.images_per_second
    typer.echo(
        f"{stats.items:,} images ({stats.unique_images:,} distinct): {stats.cache_hits:,} from cache, "
        f"{stats.embedded:,} embedded, {stats.failed} failed, {len(skipped)} undecodable at ingest"
    )
    if rate is not None:
        typer.echo(
            f"throughput {rate:.1f} images/s overall, {stats.model_images_per_second or 0:.1f} "
            f"images/s in the model; wall {stats.wall_seconds:.0f} s"
        )
    typer.echo(f"cache: {stats.cache_files:,} files, {stats.cache_bytes / 1e6:.1f} MB")
    peak = timings[-1].peak_ram_bytes
    if peak is not None:
        typer.echo(f"peak RAM {peak / 1e9:.2f} GB")
    for failure in result.failures:
        typer.echo(
            f"FAILED {failure.source}:{failure.item_id} [{failure.stage}] {failure.error}", err=True
        )
