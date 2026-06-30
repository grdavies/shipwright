#!/usr/bin/env python3
"""Dual-run shadow harness — legacy vs selector per migration family (PRD 021 TR9). """
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
    from capability_migration_parity import dual_run

    root = Path(sys.argv[1])
    family = sys.argv[2]
    ctx = json.loads(sys.argv[3] or "{}")
    result = dual_run(family, ctx, repo_root=root, skip_freshness=False)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result.get("match") else 1)
    return 0

if __name__ == "__main__":
    run_module_main(main)
