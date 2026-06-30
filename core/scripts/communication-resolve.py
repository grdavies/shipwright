#!/usr/bin/env python3
"""Deprecated wrapper forwarding to resolve-intensity."""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
from _sw.cli import run_module_main

def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h","--help"):
        print("Usage: communication-resolve <command> [--config PATH] [--child CMD]"); return 0
    return subprocess.run([sys.executable, str(SCRIPT_DIR/"resolve-intensity.py"), "--command", args[0], *args[1:]]).returncode
if __name__ == "__main__": run_module_main(main)
