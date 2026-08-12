#!/usr/bin/env python3
"""Thin host shim — invoke Shipwright scripts via the versioned zipapp."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_PLUGIN_ROOT_ENV = "CLAUDE_PLUGIN_ROOT"


def _resolve_pyz(plugin_root: Path) -> Path:
    stable = plugin_root / "shipwright.pyz"
    if stable.is_file():
        return stable
    candidates = sorted(plugin_root.glob("shipwright-*.pyz"))
    if not candidates:
        raise FileNotFoundError(f"no shipwright.pyz under {plugin_root}")
    return candidates[-1]


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: sw-run.py <script.py> [args...]", file=sys.stderr)
        return 2
    plugin_root = Path(
        os.environ.get(_PLUGIN_ROOT_ENV, Path(__file__).resolve().parent.parent)
    )
    pyz = _resolve_pyz(plugin_root)
    env = os.environ.copy()
    env.setdefault(_PLUGIN_ROOT_ENV, str(plugin_root))
    cmd = [sys.executable, str(pyz), *sys.argv[1:]]
    return subprocess.call(cmd, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
