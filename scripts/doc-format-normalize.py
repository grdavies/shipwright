#!/usr/bin/env python3
"""CLI wrapper for doc_format.py"""
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
    import doc_format
    if args and args[0] == "--check":
        return doc_format.main(["check", *args[1:]])
    if args and args[0] == "--write":
        rest = args[1:]
        if rest and rest[0] == "--inplace": return doc_format.main(["write", *rest[1:], "--inplace"])
        return doc_format.main(["write", *rest])
    return doc_format.main(args)
if __name__ == "__main__": run_module_main(main)
