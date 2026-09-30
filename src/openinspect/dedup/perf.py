"""Runtime and peak memory of the audit stages (M3L)."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from openinspect.dedup.audit_models import Performance, StageTimingInfo


def peak_memory_bytes() -> int | None:
    """Peak resident memory of this process so far, or ``None`` if the platform cannot tell."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        kernel32 = ctypes.WinDLL("kernel32")
        psapi = ctypes.WinDLL("psapi")
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCounters),
            wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        ok = psapi.GetProcessMemoryInfo(
            kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        )
        return int(counters.PeakWorkingSetSize) if ok else None
    import resource

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak) if sys.platform == "darwin" else int(peak) * 1024


@dataclass(frozen=True)
class StageTiming:
    stage: str
    seconds: float
    peak_ram_bytes: int | None  # peak of the whole process up to the end of the stage


@contextmanager
def timed(stage: str, sink: list[StageTiming]) -> Iterator[None]:
    """Record the wall time of a block and the process's peak memory at its end."""
    started = time.perf_counter()
    try:
        yield
    finally:
        sink.append(StageTiming(stage, time.perf_counter() - started, peak_memory_bytes()))


def cpu_name() -> str | None:
    """A readable processor name (the platform module only gives a family code on Windows)."""
    if sys.platform == "win32":
        import winreg

        try:
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            )
            value, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            return str(value).strip() or None
        except OSError:  # pragma: no cover - the key exists on every Windows machine
            return None
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:  # pragma: no cover - macOS and others
        pass
    return platform.processor() or None  # pragma: no cover


def code_version(repo_root: Path) -> tuple[str | None, bool | None]:
    """(commit id of HEAD, whether tracked files differ from it); ``(None, None)`` outside git."""
    git = shutil.which("git")
    if git is None:  # pragma: no cover - git is installed wherever the repository is
        return None, None
    try:
        head = subprocess.run(  # noqa: S603 - fixed arguments, no shell
            [git, "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True, check=True
        ).stdout.strip()
        status = subprocess.run(  # noqa: S603 - fixed arguments, no shell
            [git, "status", "--porcelain", "--untracked-files=no"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None, None
    return head or None, bool(status)


RunRecord = dict[str, object]


def runs_file(data_dir: Path, kind: str) -> Path:
    return data_dir / "m3" / "runs" / f"{kind}.jsonl"


def append_run(data_dir: Path, kind: str, record: RunRecord) -> None:
    """Keep one JSON line per run of a stage (``features``, ``synthetic``) for the performance report."""
    path = runs_file(data_dir, kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def read_runs(data_dir: Path, kind: str) -> list[RunRecord]:
    path = runs_file(data_dir, kind)
    if not path.is_file():
        return []
    rows: list[RunRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
    return rows


def _number(record: RunRecord, key: str) -> float | None:
    value = record.get(key)
    return float(value) if isinstance(value, int | float) else None


def _integer(record: RunRecord, key: str) -> int | None:
    value = _number(record, key)
    return None if value is None else int(value)


def build_performance(
    timings: Sequence[StageTiming],
    *,
    features_runs: Sequence[RunRecord],
    synthetic_runs: Sequence[RunRecord],
    cache_files: int,
    cache_bytes: int,
    dim: int,
) -> Performance:
    """Stage times of this analysis next to the recorded runs that did the embedding work.

    Of the ``features`` and ``synthetic`` runs, the one that embedded the most images is reported:
    later runs read the caches and their time says nothing about the model.
    """
    stages: list[StageTimingInfo] = []
    build = max(features_runs, key=lambda r: _number(r, "embedded") or 0.0, default=None)
    if build is not None and (_number(build, "embedded") or 0) > 0:
        stages.append(
            StageTimingInfo(
                stage="embeddings (cache build)",
                seconds=_number(build, "wall_seconds") or 0.0,
                peak_ram_bytes=_integer(build, "peak_ram_bytes"),
                images=_integer(build, "embedded"),
                note=str(build["note"]) if build.get("note") else None,
            )
        )
    copies = max(synthetic_runs, key=lambda r: _number(r, "embedded") or 0.0, default=None)
    if copies is not None:
        stages.append(
            StageTimingInfo(
                stage="synthetic copies",
                seconds=_number(copies, "wall_seconds") or 0.0,
                peak_ram_bytes=_integer(copies, "peak_ram_bytes"),
                images=_integer(copies, "embedded"),
                note=str(copies["note"]) if copies.get("note") else None,
            )
        )
    stages.extend(
        StageTimingInfo(stage=t.stage, seconds=round(t.seconds, 3), peak_ram_bytes=t.peak_ram_bytes)
        for t in timings
    )
    peaks = [s.peak_ram_bytes for s in stages if s.peak_ram_bytes is not None]
    return Performance(
        stages=stages,
        total_seconds=round(sum(s.seconds for s in stages), 3),
        embed_images_per_second=None if build is None else _number(build, "images_per_second"),
        embed_model_images_per_second=None
        if build is None
        else _number(build, "model_images_per_second"),
        cache_files=cache_files,
        cache_bytes=cache_bytes,
        cache_logical_bytes=cache_files * dim * 4,
        peak_ram_bytes=max(peaks) if peaks else None,
        cpu=cpu_name(),
        note=f"{os.cpu_count()} logical processors; peak RAM is the peak of the process up to the end of a stage",
    )
