#!/usr/bin/env python3
"""Related-units scanner"""
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
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h","--help"):
        print("planning-related scan|confirm|list-emission-points"); return 0
    if args[0] not in ("scan","confirm","list-emission-points"):
        print("unknown subcommand", file=sys.stderr); return 2
    os.environ["PYTHONPATH"] = str(SCRIPT_DIR) + (":"+os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else "")
    import planning_related
    return planning_related.main([str(git_root()), *args])
if __name__ == "__main__": run_module_main(main)
