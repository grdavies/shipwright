#!/usr/bin/env python3
"""Back-compat wrapper around dispatch-check."""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
from _sw.cli import run_module_main

def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    return subprocess.run([sys.executable, str(SCRIPT_DIR/"dispatch-check.py"), *args]).returncode
if __name__ == "__main__": run_module_main(main)
