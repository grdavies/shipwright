#!/usr/bin/env python3
"""Safe cleanup of merged branches, stale worktrees, and terminal deliver run-state."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main


def git_root() -> Path:
    proc = subprocess.run(["git", "-C", str(Path.cwd()), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return Path(proc.stdout.strip()) if proc.returncode == 0 and proc.stdout.strip() else SCRIPT_DIR.parent


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    root = git_root()
    import cleanup_lib
    old_argv = sys.argv
    try:
        sys.argv = [str(Path(__file__).name), str(root), *args]
        cleanup_lib.main()
    finally:
        sys.argv = old_argv
    return 0


if __name__ == "__main__":
    run_module_main(main)
