"""Locations outside the repository: the data directory and the guards around it.

Raw data never goes into the repository and never into a OneDrive folder. The directory comes from
``--data-dir``, then the ``OPENINSPECT_DATA_DIR`` environment variable, then a ``.env`` file in the
repository root.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Mapping
from pathlib import Path

ENV_VAR = "OPENINSPECT_DATA_DIR"
ONEDRIVE_VARS = ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")
GIB = 1 << 30


class DataDirError(Exception):
    """The data directory is missing, unsafe or too small."""


def parse_dotenv(text: str) -> dict[str, str]:
    """Minimal ``.env`` reader: ``KEY=VALUE`` lines, ``#`` comment lines, optional quotes."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def _is_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def check_data_dir(path: Path, *, repo_root: Path, environ: Mapping[str, str]) -> None:
    """Refuse relative paths, paths inside the repository and paths inside a OneDrive folder."""
    if not path.is_absolute():
        raise DataDirError(f"the data directory must be an absolute path, got {path}")
    if _is_inside(path, repo_root):
        raise DataDirError(f"the data directory {path} is inside the repository {repo_root}")
    for name in ONEDRIVE_VARS:
        root = environ.get(name)
        if root and _is_inside(path, Path(root)):
            raise DataDirError(f"the data directory {path} is inside OneDrive ({root})")
    if any(part.lower().startswith("onedrive") for part in path.parts):
        raise DataDirError(f"the data directory {path} is inside a OneDrive folder")


def resolve_data_dir(
    explicit: Path | None,
    *,
    repo_root: Path,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """The data directory: ``explicit``, else ``$OPENINSPECT_DATA_DIR``, else ``<repo>/.env``."""
    env = os.environ if environ is None else environ
    if explicit is not None:
        chosen = explicit
    elif env.get(ENV_VAR):
        chosen = Path(env[ENV_VAR])
    else:
        dotenv = repo_root / ".env"
        values = parse_dotenv(dotenv.read_text(encoding="utf-8")) if dotenv.is_file() else {}
        if not values.get(ENV_VAR):
            raise DataDirError(
                f"{ENV_VAR} is not set: pass --data-dir, set the variable, or put it in .env "
                "(an absolute path outside the repository and outside OneDrive, "
                "e.g. C:\\data\\openinspect)"
            )
        chosen = Path(values[ENV_VAR])
    check_data_dir(chosen, repo_root=repo_root, environ=env)
    return chosen


def ensure_free_space(path: Path, needed: int, *, margin: int = GIB) -> None:
    """Fail when the drive that holds ``path`` has less than ``needed + margin`` bytes free."""
    anchor = next((p for p in (path, *path.parents) if p.exists()), None)
    if anchor is None:
        raise DataDirError(f"cannot find an existing parent of {path}")
    free = shutil.disk_usage(anchor).free
    if free < needed + margin:
        raise DataDirError(
            f"not enough free space on the drive of {anchor}: {free / GIB:.1f} GiB free, "
            f"{(needed + margin) / GIB:.1f} GiB needed"
        )
