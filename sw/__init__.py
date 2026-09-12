"""Shipwright packaged console — version re-exported from scripts.version."""

from __future__ import annotations

import importlib.metadata
import importlib.util
from pathlib import Path

# Fallback floor when scripts/version.py is absent (should match scripts/version.py).
_PYTHON_FLOOR_FALLBACK = "3.10"


def _version_paths() -> list[Path]:
    here = Path(__file__).resolve().parent
    return [
        here.parent / "scripts" / "version.py",
        here / "scripts" / "version.py",
    ]


def _load_version_module():
    errors: list[str] = []
    for path in _version_paths():
        if not path.is_file():
            continue
        spec = importlib.util.spec_from_file_location("_shipwright_version", path)
        if spec is None or spec.loader is None:
            errors.append(f"cannot load spec from {path}")
            continue
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    tried = ", ".join(p.as_posix() for p in _version_paths())
    detail = "; ".join(errors) if errors else "no version module found"
    raise RuntimeError(f"cannot load version metadata ({detail}); tried: {tried}")


def _version_from_metadata() -> str | None:
    for dist_name in ("shipwright", "shipwright-workflow"):
        try:
            return importlib.metadata.version(dist_name)
        except importlib.metadata.PackageNotFoundError:
            continue
    return None


try:
    _v = _load_version_module()
    __version__ = _v.__version__
    PYTHON_FLOOR = _v.PYTHON_FLOOR
except RuntimeError:
    meta_version = _version_from_metadata()
    if not meta_version:
        raise
    __version__ = meta_version
    PYTHON_FLOOR = _PYTHON_FLOOR_FALLBACK

__all__ = ["PYTHON_FLOOR", "__version__"]
