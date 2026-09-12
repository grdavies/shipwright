"""Shipwright packaged console — version re-exported from scripts.version."""

from __future__ import annotations

import importlib.util
from pathlib import Path


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


_v = _load_version_module()
__version__ = _v.__version__
PYTHON_FLOOR = _v.PYTHON_FLOOR

__all__ = ["PYTHON_FLOOR", "__version__"]
