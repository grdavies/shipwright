#!/usr/bin/env python3
"""Provider-conditional source-of-truth resolver (PRD 015) — decision class only."""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main
from memory_sot import main

if __name__ == "__main__":
    run_module_main(main)
