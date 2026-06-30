#!/usr/bin/env python3
"""Deterministic doc-review persona selection via capability selector (PRD 021 phase 6). """
from __future__ import annotations
import sys
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from _sw.cli import run_module_main

def main(argv: list[str] | None = None) -> int:
    import json, sys
    from pathlib import Path

    sys.path.insert(0, sys.argv[1] + "/scripts")
    from capability_migration_parity import select_family

    root = Path(sys.argv[1])
    raw = sys.argv[2] or "{}"
    ctx = json.loads(raw)
    out = select_family("doc-review", ctx, repo_root=root, skip_freshness=False)
    print(json.dumps(out, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0

if __name__ == "__main__":
    run_module_main(main)
