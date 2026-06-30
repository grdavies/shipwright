#!/usr/bin/env python3
"""Per-worktree Shipwright state."""
from __future__ import annotations
import sys
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from _sw.cli import run_module_main

def main(argv: list[str] | None = None) -> int:
    import shipwright_state_lib as ssl
    return ssl.main(argv)
    return 0

if __name__ == "__main__":
    run_module_main(main)
