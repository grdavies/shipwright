#!/usr/bin/env python3
"""Deterministic R41 redaction chokepoint — stdin or file arg → stdout (redacted)."""
from __future__ import annotations

import os
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
    args = list(argv if argv is not None else sys.argv[1:])
    if os.environ.get("SW_HARNESS") == "1" and "--destination" not in args:
        args = ["--destination", "external", *args]
    import memory_redact
    old_argv = sys.argv
    try:
        sys.argv = [str(Path(__file__).name), *args]
        return memory_redact.main()
    finally:
        sys.argv = old_argv


if __name__ == "__main__":
    run_module_main(main)
