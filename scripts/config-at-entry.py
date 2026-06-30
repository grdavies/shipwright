#!/usr/bin/env python3
"""Shared at-entry nudge for stale config."""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
from _sw.cli import run_module_main

def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    quiet = "--quiet" in args
    root = SCRIPT_DIR.parent
    config = next((p for p in (root/".cursor/workflow.config.json", root/"workflow.config.json") if p.is_file()), None)
    sw_cfg = SCRIPT_DIR/"sw-configure.py"
    if not sw_cfg.is_file(): return 0
    proc = subprocess.run([sys.executable, str(sw_cfg), "drift-check", "--config", str(config or "/nonexistent")], capture_output=True, text=True)
    try: stale = json.loads(proc.stdout or "{}").get("stale", False)
    except json.JSONDecodeError: stale = False
    if stale and not quiet: print("config may be stale; run /sw-init to refresh")
    return 0
if __name__ == "__main__": run_module_main(main)
