#!/usr/bin/env python3
"""Route substantive docs edits"""
from __future__ import annotations
import subprocess, sys, os
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path: sys.path.insert(0, str(SCRIPT_DIR))
from _sw.cli import run_module_main

def git_root():
    p = subprocess.run(["git","-C",str(Path.cwd()),"rev-parse","--show-toplevel"], capture_output=True, text=True)
    return Path(p.stdout.strip()) if p.returncode==0 else SCRIPT_DIR.parent

def main(argv=None):
    import docs_edit_route as der
    return der.main(argv)
if __name__ == "__main__": run_module_main(main)
