#!/usr/bin/env python3
"""Deterministic verification-gate verdict helper (IM1 / U1; hardened plan 005). """
from __future__ import annotations
import sys
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from _sw.cli import run_module_main

def main(argv: list[str] | None = None) -> int:
    import json, sys
    head = set(json.loads(sys.argv[1]))
    base = set(json.loads(sys.argv[2]))
    # Exit 0 when head introduces a failing command not present at baseline.
    sys.exit(0 if not head <= base else 1)
    return 0

if __name__ == "__main__":
    run_module_main(main)
