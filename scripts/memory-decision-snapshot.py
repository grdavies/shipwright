#!/usr/bin/env python3
"""Redacted decision snapshot writer for freeze path (PRD 015 R4–R6). Offline-safe — no provider calls."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main


def git_root() -> Path:
    proc = subprocess.run(
        ["git", "-C", str(Path.cwd()), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip())
    return SCRIPT_DIR.parent


def repo_root() -> Path:
    return git_root()


def main(argv: list[str] | None = None) -> int:
    import memory_decision_snapshot
    from _sw.cli import delegate_argv_main
    return delegate_argv_main(memory_decision_snapshot.main, argv, prog="memory-decision-snapshot.py")


if __name__ == "__main__":
    run_module_main(main)
