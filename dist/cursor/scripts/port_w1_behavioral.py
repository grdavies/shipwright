#!/usr/bin/env python3
"""Materialize W1 behavioral harnesses from git and wire pytest entrypoints (PRD 054 3.1)."""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from port_wave_behavioral import port_wave, repo_root


def port_w1(root: Path) -> int:
    return port_wave(root, "W1")


def main() -> int:
    return port_w1(repo_root())


if __name__ == "__main__":
    raise SystemExit(main())
