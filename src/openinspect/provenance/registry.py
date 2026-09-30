"""Load, write and look up source manifests."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import ValidationError

from openinspect.provenance.schema import SourceManifest

MANIFESTS_SUBDIR = Path("manifests") / "sources"
HEADER = (
    "# Source manifest written by `openinspect source add`.\n"
    "# Field semantics: manifests/sources/_template.yaml and docs/DATASET_INTAKE.md.\n"
)

Level = Literal["error", "warning"]


@dataclass(frozen=True)
class Issue:
    """One finding of the loader or the validator."""

    level: Level
    code: str
    message: str
    slug: str | None = None
    where: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "level": self.level,
            "code": self.code,
            "slug": self.slug,
            "where": self.where,
            "message": self.message,
        }


@dataclass(frozen=True)
class LoadedManifest:
    path: Path
    manifest: SourceManifest


@dataclass(frozen=True)
class Registry:
    """All manifests found under ``<root>/manifests/sources`` plus what went wrong while loading."""

    root: Path
    loaded: tuple[LoadedManifest, ...]
    issues: tuple[Issue, ...]

    def get(self, slug: str) -> LoadedManifest | None:
        return next((lm for lm in self.loaded if lm.manifest.slug == slug), None)

    @property
    def slugs(self) -> list[str]:
        return sorted(lm.manifest.slug for lm in self.loaded)


class DuplicateSourceError(Exception):
    """A source with this slug already exists."""


def manifests_dir_for(root: Path) -> Path:
    return root / MANIFESTS_SUBDIR


def find_repo_root(start: Path | None = None) -> Path:
    """Nearest parent of ``start`` (default: cwd) that holds ``manifests/sources``."""
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if manifests_dir_for(candidate).is_dir():
            return candidate
    return here


def rel_path(path: Path, root: Path) -> str:
    """POSIX path of ``path`` relative to ``root`` (or the path itself when it lies outside)."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def schema_issues(exc: ValidationError, slug: str | None, where: str | None) -> list[Issue]:
    """Turn a Pydantic error into one :class:`Issue` per problem, with readable messages."""
    issues: list[Issue] = []
    for error in exc.errors(include_url=False):
        location = ".".join(str(part) for part in error["loc"]) or "<manifest>"
        message = str(error["msg"]).removeprefix("Value error, ")
        issues.append(Issue("error", "E_SCHEMA", f"{location}: {message}", slug, where))
    return issues


def parse_manifest_text(
    text: str, where: str | None = None
) -> tuple[SourceManifest | None, list[Issue]]:
    """Parse YAML text into a manifest. Returns ``(None, issues)`` when it is not usable."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        first_line = str(exc).strip().splitlines()[0] if str(exc).strip() else "syntax error"
        return None, [Issue("error", "E_YAML", f"invalid YAML: {first_line}", None, where)]
    if not isinstance(data, dict):
        return None, [Issue("error", "E_YAML", "the top level must be a mapping", None, where)]
    slug = data.get("slug") if isinstance(data.get("slug"), str) else None
    try:
        return SourceManifest.model_validate(data), []
    except ValidationError as exc:
        return None, schema_issues(exc, slug, where)


def load_registry(root: Path) -> Registry:
    """Load every ``*.yaml`` manifest (files starting with ``_`` are templates and are skipped)."""
    directory = manifests_dir_for(root)
    files = sorted(directory.glob("*.yaml")) if directory.is_dir() else []
    loaded: list[LoadedManifest] = []
    issues: list[Issue] = []
    for path in files:
        if path.name.startswith("_"):
            continue
        where = rel_path(path, root)
        manifest, found = parse_manifest_text(path.read_text(encoding="utf-8"), where)
        issues.extend(found)
        if manifest is None:
            continue
        if manifest.slug != path.stem:
            issues.append(
                Issue(
                    "error",
                    "E_SLUG_FILENAME",
                    f"slug {manifest.slug!r} does not match the file name {path.name!r}",
                    manifest.slug,
                    where,
                )
            )
        loaded.append(LoadedManifest(path, manifest))
    by_slug: dict[str, list[str]] = {}
    for item in loaded:
        by_slug.setdefault(item.manifest.slug, []).append(rel_path(item.path, root))
    for slug, paths in sorted(by_slug.items()):
        if len(paths) > 1:
            issues.append(
                Issue(
                    "error",
                    "E_DUPLICATE_SLUG",
                    f"slug {slug!r} is declared in {len(paths)} files: {', '.join(paths)}",
                    slug,
                    paths[0],
                )
            )
    return Registry(root=root, loaded=tuple(loaded), issues=tuple(issues))


def dump_manifest(manifest: SourceManifest) -> str:
    """Serialise a manifest as YAML (dates stay dates, key order follows the schema)."""
    body = yaml.safe_dump(
        manifest.model_dump(mode="python"), sort_keys=False, allow_unicode=True, width=100
    )
    return HEADER + body


def _atomic_write(path: Path, text: str) -> None:
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(text.encode("utf-8"))
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def add_manifest(root: Path, manifest: SourceManifest, *, force: bool = False) -> Path:
    """Write ``manifests/sources/<slug>.yaml``; a duplicate slug raises unless ``force`` is set.

    ``force`` only replaces the file named after the slug. A slug that is already declared inside a
    differently named file is always refused, because that would leave two files with one id.
    """
    directory = manifests_dir_for(root)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{manifest.slug}.yaml"
    clash = load_registry(root).get(manifest.slug)
    if clash is not None and clash.path.resolve() != target.resolve():
        raise DuplicateSourceError(
            f"source id {manifest.slug!r} is already declared in {rel_path(clash.path, root)}"
        )
    if target.exists() and not force:
        raise DuplicateSourceError(
            f"source {manifest.slug!r} already exists ({rel_path(target, root)}); "
            "use --force to replace it"
        )
    _atomic_write(target, dump_manifest(manifest))
    return target
