#!/usr/bin/env python3
"""GAP-BACKLOG helper"""
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
        print("gap-backlog list|check|flip"); return 0
    if args[0] not in ("list","check","flip"):
        print('{"verdict":"fail","error":"unknown subcommand"}', file=sys.stderr); return 2
    import gap_backlog
    return gap_backlog.main(["--root", str(git_root()), *args])
if __name__ == "__main__": run_module_main(main)
