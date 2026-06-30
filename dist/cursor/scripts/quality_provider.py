#!/usr/bin/env python3
"""Quality harness adapter selector (PRD 039)."""
from __future__ import annotations
import json, os, subprocess, sys
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path: sys.path.insert(0, str(SCRIPT_DIR))
from _sw.cli import run_module_main
import sw_resolve_plugin_root as spr

def cfg(config: Path | None, key: str, default: str) -> str:
    if config and config.is_file():
        try:
            data = json.loads(config.read_text(encoding="utf-8"))
            cur = data
            for part in key.strip(".").split("."):
                if isinstance(cur, dict) and part in cur: cur = cur[part]
                else: return default
            return str(cur) if cur is not None else default
        except json.JSONDecodeError: return default
    return default

def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    plugin_root = spr.resolve_plugin_root(SCRIPT_DIR)
    p = subprocess.run(["git","rev-parse","--show-toplevel"], capture_output=True, text=True)
    root = Path(p.stdout.strip()) if p.returncode==0 else Path.cwd()
    config = None
    i = 0
    while i < len(args):
        if args[i] == "--config" and i+1 < len(args): config = Path(args[i+1]); i += 2
        elif args[i] in ("-h","--help"): print("usage: quality-provider.py [--config PATH]"); return 0
        else: print(json.dumps({"verdict":"none","reason":"unknown argument"}), file=sys.stderr); return 2
    if config is None:
        for c in (root/".cursor/workflow.config.json", root/"workflow.config.json"):
            if c.is_file(): config = c; break
    provider = cfg(config, "quality.provider", "none").strip().lower()
    if provider in ("", "none", "off", "unconfigured", "null"):
        adapter = plugin_root/"core/providers/quality/none.py"
        if not adapter.is_file(): adapter = plugin_root/"providers/quality/none.py"
        proc = subprocess.run([sys.executable, str(adapter)], capture_output=True, text=True)
        sys.stdout.write(proc.stdout or json.dumps({"verdict":"none","provider":"none","skipped":True}))
        return 0
    if provider == "auto":
        print(json.dumps({"verdict":"none","provider":"auto","skipped":True,"reason":"builtin reserved Phase 2"}))
        return 0
    adapter = plugin_root/f"core/providers/quality/{provider}.py"
    if not adapter.is_file(): adapter = plugin_root/f"providers/quality/{provider}.py"
    if not adapter.is_file():
        print(json.dumps({"verdict":"none","provider":provider,"skipped":True,"reason":"unknown quality provider"}))
        return 2
    proc = subprocess.run([sys.executable, str(adapter)], capture_output=True, text=True)
    sys.stdout.write(proc.stdout)
    return proc.returncode
if __name__ == "__main__": run_module_main(main)
