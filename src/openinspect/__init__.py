"""OpenInspect-Trust: provenance-aware cross-dataset benchmark tooling."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("openinspect-trust")
except PackageNotFoundError:  # pragma: no cover - only when run from an unbuilt source tree
    __version__ = "0+unknown"

__all__ = ["__version__"]
