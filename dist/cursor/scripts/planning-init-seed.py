#!/usr/bin/env python3
"""Seed planning visibility profile, store backend, and privacy notice (PRD 034 R21). """
from __future__ import annotations
import sys
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from _sw.cli import run_module_main

def main(argv: list[str] | None = None) -> int:
    import json
    import shutil
    import subprocess
    import sys
    from pathlib import Path

    root = Path(sys.argv[1])
    config_path = Path(sys.argv[2])
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(cfg, dict):
        raise SystemExit(json.dumps({"verdict": "fail", "error": "invalid-workflow-config"}))

    planning = cfg.get("planning")
    if not isinstance(planning, dict):
        planning = {}
    store = planning.get("store")
    if not isinstance(store, dict):
        store = {}
    if not store.get("backend"):
        store["backend"] = "in-repo-public"
    planning["store"] = store
    cfg["planning"] = planning
    config_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    return 0

if __name__ == "__main__":
    run_module_main(main)
