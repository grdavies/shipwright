#!/usr/bin/env python3
"""Allowlisted generate step for build-chain sync (PRD 060 R12)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _sw.cli import run_module_main


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parent.parent
    return subprocess.run([sys.executable, "-m", "sw", "generate", "--all"], cwd=str(root)).returncode


if __name__ == "__main__":
    run_module_main(main)
