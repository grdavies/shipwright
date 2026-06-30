#!/usr/bin/env python3
"""Kernel classification + orchestrator-step-plan completeness (PRD 024 TR8)."""
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
    sys.path.insert(0, str(Path(sys.argv[1]) / "scripts"))
    from orchestrator_step_plan import lint_orchestrator_kernel_completeness
    root = Path(sys.argv[1])
    ok, missing = lint_orchestrator_kernel_completeness(root)
    if not ok:
        print(json.dumps({"verdict": "fail", "failures": [f"unclassified orchestrator plan steps: {', '.join(missing)}"]}, indent=2))
        sys.exit(1)
    from orchestrator_guidelines import lint_orchestrator_packs
    ok_packs, pack_failures = lint_orchestrator_packs(root)
    if not ok_packs:
        print(json.dumps({"verdict": "fail", "failures": pack_failures}, indent=2))
        sys.exit(1)
    print(json.dumps({"verdict": "pass"}))
    return 0

if __name__ == "__main__":
    run_module_main(main)
