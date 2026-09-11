#!/usr/bin/env python3
"""Claude Code installer entrypoint — delegates to packaged install.py (PRD 338 R29)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
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
    env = os.environ.copy()
    env.setdefault(_PLUGIN_ROOT_ENV, str(_PLUGIN_ROOT))
    pyz = _resolve_pyz(_PLUGIN_ROOT)
    cmd = [
        sys.executable,
        str(pyz),
        "install.py",
        "--integration",
        "claude-code",
        *sys.argv[1:],
    ]
    return subprocess.call(cmd, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
