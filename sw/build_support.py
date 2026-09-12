"""Setuptools build_py hook — always sync runtime bundle before packaging.

Ensures ``uv tool install`` / plain PEP 517 builds from git include
``sw/scripts/version.py`` and other runtime mirrors (PRD 345 R2).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from setuptools.command.build_py import build_py as _build_py


def _sync_runtime_bundle(root: Path) -> None:
    path = root / "scripts" / "runtime_requirements.py"
    spec = importlib.util.spec_from_file_location("_sw_runtime_requirements", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load runtime_requirements from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    result = mod.sync_runtime_bundle(root)
    if result.get("verdict") != "pass":
        raise RuntimeError(f"sync_runtime_bundle failed: {result!r}")


class build_py(_build_py):
    def run(self) -> None:  # noqa: D401 — setuptools API
        root = Path(__file__).resolve().parents[1]
        _sync_runtime_bundle(root)
        super().run()
