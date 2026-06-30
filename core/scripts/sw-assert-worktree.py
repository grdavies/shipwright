#!/usr/bin/env python3
"""Fail-closed guard: block implementation entry on bare default-branch checkout (PRD 002 R6/R27). """
from __future__ import annotations
import sys
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from _sw.cli import run_module_main

def main(argv: list[str] | None = None) -> int:
    import json
    import sys
    from pathlib import Path

    root = Path(sys.argv[1])
    for candidate in (root / ".cursor/workflow.config.json", root / "workflow.config.json"):
        if candidate.is_file():
            try:
                cfg = json.loads(candidate.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                break
            print(cfg.get("defaultBaseBranch", "main"))
            raise SystemExit
    print("main")
    return 0

if __name__ == "__main__":
    run_module_main(main)
