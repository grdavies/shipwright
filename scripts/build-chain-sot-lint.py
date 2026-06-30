#!/usr/bin/env python3
"""Validate core/sw-reference/build-chain-sot.json."""
from __future__ import annotations
import json, sys
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
from _sw.cli import run_module_main

def main(argv=None):
    root = SCRIPT_DIR.parent
    manifest = root/"core/sw-reference/build-chain-sot.json"
    sw_ref = root/"core/sw-reference"
    if not manifest.is_file():
        print(f"FAIL build-chain-sot-lint: missing {manifest}"); return 1
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if not data.get("version") or not data.get("coreAuthoredAllowlist"):
        print("FAIL build-chain-sot-lint: manifest missing version or coreAuthoredAllowlist"); return 1
    seen, fail = set(), 0
    for entry in data.get("coreAuthoredAllowlist", []):
        if entry in seen:
            print(f"FAIL build-chain-sot-lint: duplicate allowlist entry: {entry}"); fail = 1; continue
        seen.add(entry)
        if entry.endswith("/"):
            if not (sw_ref/entry.rstrip("/")).is_dir():
                print(f"FAIL build-chain-sot-lint: allowlist directory missing: core/sw-reference/{entry}"); fail = 1
        elif not (sw_ref/entry).is_file():
            print(f"FAIL build-chain-sot-lint: allowlist file missing: core/sw-reference/{entry}"); fail = 1
    if fail == 0: print("OK  build-chain-sot-lint")
    return fail
if __name__ == "__main__": run_module_main(main)
