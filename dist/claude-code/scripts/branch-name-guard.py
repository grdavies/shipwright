#!/usr/bin/env python3
"""Branch-name conformance guard."""
from __future__ import annotations
import sys
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path: sys.path.insert(0, str(SCRIPT_DIR))
from _sw.cli import run_module_main
import branch_name_guard
def main(argv=None): return branch_name_guard.main(argv)
if __name__ == "__main__": run_module_main(main)
