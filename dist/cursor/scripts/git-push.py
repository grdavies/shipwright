#!/usr/bin/env python3
"""Workflow push wrapper with secret scan chokepoint."""
from __future__ import annotations
import subprocess, sys, os
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path: sys.path.insert(0, str(SCRIPT_DIR))
from _sw.cli import run_module_main

def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path.cwd()
    p = subprocess.run(["git","rev-parse","--show-toplevel"], capture_output=True, text=True)
    if p.returncode==0: root = Path(p.stdout.strip())
    os.environ["PYTHONPATH"] = str(SCRIPT_DIR) + (":" + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else "")
    mat = SCRIPT_DIR / "planning_materialize.py"
    if mat.is_file():
        subprocess.run([sys.executable, str(mat), "--root", str(root), "guard-staged", "--push"], check=False)
    scan = subprocess.run([sys.executable, str(SCRIPT_DIR / "secret-scan.py"), "pre-push"])
    if scan.returncode != 0:
        return scan.returncode
    return subprocess.run(["git","push",*args]).returncode
if __name__ == "__main__": run_module_main(main)
