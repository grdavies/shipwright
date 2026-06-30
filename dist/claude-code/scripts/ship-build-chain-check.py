#!/usr/bin/env python3
"""Fail closed when build-chain paths drift before ship commit."""
from __future__ import annotations
import json, os, subprocess, sys
from pathlib import Path
from _sw.cli import run_module_main

def main(argv=None):
    root = Path(__file__).resolve().parent.parent
    manifest = Path(os.environ.get("BUILD_CHAIN_PATHS_MANIFEST", str(root/"core/sw-reference/build-chain-paths.json")))
    if not manifest.is_file():
        print(f"ship-build-chain-check: missing {manifest}", file=sys.stderr); return 2
    data = json.loads(manifest.read_text(encoding="utf-8"))
    prefixes = data.get("pathPrefixes") or []
    proc = subprocess.run(["git","-C",str(root),"status","--porcelain"], capture_output=True, text=True)
    changed = [line[3:] for line in proc.stdout.splitlines() if line.strip()]
    if not any(any(p and path.startswith(p) for p in prefixes) for path in changed):
        print("ship-build-chain-check: no build-chain paths in diff — skip"); return 0
    if subprocess.run([sys.executable, str(root/"scripts/build-chain-sync.py"), "--check"], cwd=str(root)).returncode == 0:
        print("ship-build-chain-check: build-chain parity OK"); return 0
    print("ship-build-chain-check: FAIL — run python3 scripts/build-chain-sync.py", file=sys.stderr); return 20
if __name__ == "__main__": run_module_main(main)
