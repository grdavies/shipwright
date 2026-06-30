#!/usr/bin/env python3
"""Pre-push secret scan chokepoint (R41/R50/R51)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if args and args[0] == "inflight-tuple":
        import inflight_signal
        root = Path.cwd()
        proc = subprocess.run(
            ["git", "-C", str(Path.cwd()), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            root = Path(proc.stdout.strip())
        inflight_signal.main([str(root), "validate", *args[1:]])
        return 0
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "secret_scan.py"), *args],
        check=False,
    )
    return proc.returncode


if __name__ == "__main__":
    run_module_main(main)
