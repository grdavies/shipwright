#!/usr/bin/env python3
"""Pre-push secret scan chokepoint (R41/R50/R51). Fail-closed on scanner error. inFlight tuple bodies are validated at write time by inflight_signal.py (PRD 032 R18)."""
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
    args = list(sys.argv[1:] if argv is None else argv)
    root = git_root()
    if args and args[0] == 'inflight-tuple':
        import inflight_signal
        inflight_signal.main([str(root), 'validate', *args[1:]])
        return 0
    import secret_scan
    secret_scan.main(args)
    return 0
    return 0


if __name__ == "__main__":
    run_module_main(main)
