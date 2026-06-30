#!/usr/bin/env python3
"""True when repo root contains .shipwright-dev sentinel."""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
from _sw.cli import run_module_main

def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args: root = Path(args[0])
    else:
        p = subprocess.run(["git","rev-parse","--show-toplevel"], capture_output=True, text=True)
        root = Path(p.stdout.strip()) if p.returncode==0 and p.stdout.strip() else Path.cwd()
    return 0 if (root/".shipwright-dev").is_file() else 1
if __name__ == "__main__": run_module_main(main)
