"""A quick look at the layout of an extracted tree (see a format before writing an adapter)."""

from __future__ import annotations

from collections import Counter
from pathlib import Path


def _suffix(path: Path) -> str:
    return path.suffix.lower() or "(none)"


def summarize_tree(root: Path, *, depth: int = 3, sample: int = 3) -> str:
    """Directories down to ``depth`` with counts per file extension and a few example names."""
    lines: list[str] = []

    def walk(directory: Path, level: int) -> None:
        files = sorted(p for p in directory.iterdir() if p.is_file())
        dirs = sorted(p for p in directory.iterdir() if p.is_dir())
        counts = Counter(_suffix(p) for p in files)
        label = directory.relative_to(root).as_posix() or "."
        shown = ", ".join(f"{ext} x{n}" for ext, n in sorted(counts.items()))
        lines.append(f"{'  ' * level}{label}/  [{len(files)} files{': ' + shown if shown else ''}]")
        if files:
            names = ", ".join(p.name for p in files[:sample])
            lines.append(f"{'  ' * (level + 1)}e.g. {names}{' ...' if len(files) > sample else ''}")
        if level < depth:
            for child in dirs:
                walk(child, level + 1)
        elif dirs:
            lines.append(f"{'  ' * (level + 1)}({len(dirs)} deeper directories not shown)")

    walk(root, 0)
    return "\n".join(lines)
