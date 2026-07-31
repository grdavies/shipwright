#!/usr/bin/env python3
"""Generate .github/workflows/pr-test-plan-ci.yml from pr-test-plan.manifest.json (PRD 016 R1–R3).

Regenerate after adding required fixtures (e.g. scripts/unit_tests/credentials/ for PRD 083 R6).
"""
from __future__ import annotations
import sys
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from _sw.cli import run_module_main

def main(argv: list[str] | None = None) -> int:
    import sys
    from pathlib import Path

    from ci_plan_gen import generate_pr_test_plan_workflow, repo_root

    args = list(sys.argv[1:] if argv is None else argv)
    manifest_path = Path(args[0])
    out_path = Path(args[1])
    root = Path(args[2]) if len(args) > 2 else repo_root()
    generate_pr_test_plan_workflow(root, manifest_path=manifest_path, out_path=out_path)
    print(f"Wrote {out_path}")
    return 0

if __name__ == "__main__":
    run_module_main(main)
