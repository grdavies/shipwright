"""Shipwright packaged console — version re-exported from scripts.version."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_version_module():
    path = Path(__file__).resolve().parent.parent / "scripts" / "version.py"
    spec = importlib.util.spec_from_file_location("_shipwright_version", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load version metadata from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_v = _load_version_module()
__version__ = _v.__version__
PYTHON_FLOOR = _v.PYTHON_FLOOR

__all__ = ["PYTHON_FLOOR", "__version__"]
