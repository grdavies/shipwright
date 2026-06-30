#!/usr/bin/env python3
"""Conventional Commit message validator (PRD 026 R25). Types single-sourced from release-please-config.json (same as branch-name-guard)."""
from __future__ import annotations
import sys
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from _sw.cli import run_module_main

def main(argv: list[str] | None = None) -> int:
    import json, sys
    try:
        data = json.load(open(sys.argv[1]))
        types = []
        for pkg in data.get("packages", {}).values():
            for sec in pkg.get("changelog-sections", []):
                t = sec.get("type")
                if t and t not in types:
                    types.append(t)
        print(" ".join(types) if types else "feat fix perf revert docs chore refactor test")
    except Exception:
        print("feat fix perf revert docs chore refactor test")
    return 0

if __name__ == "__main__":
    run_module_main(main)
