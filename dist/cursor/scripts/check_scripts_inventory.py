#!/usr/bin/env python3
"""Release-blocking guard for scripts call-site inventory (PRD 078 TR9, R9, KD6).

Rejects unclassified consumer-context literals in source and dist trees; wired for
pr-ci via suite-registry and consumed by check-gate required-job policy.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main
from sw_scripts_inventory import (
    find_dist_mismatches,
    find_unclassified,
    load_inventory,
    repo_root,
)


def run_check(root: Path) -> tuple[int, dict]:
    try:
        inventory = load_inventory(root)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        return 20, {
            "verdict": "fail",
            "reason": "inventory-load-failed",
            "error": str(exc),
        }

    violations: list[dict] = []
    violations.extend(find_unclassified(root, inventory))
    violations.extend(find_dist_mismatches(root))

    if violations:
        return 20, {
            "verdict": "fail",
            "reason": "scripts-inventory-guard",
            "violationCount": len(violations),
            "violations": violations[:50],
        }
    return 0, {
        "verdict": "pass",
        "reason": "scripts-inventory-closed",
        "entryCount": len(inventory.get("entries") or []),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="check_scripts_inventory.py")
    parser.add_argument("--check", action="store_true", help="Run inventory guard (default)")
    parser.add_argument("--root", default=".", help="Repository root")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    root = repo_root(Path(args.root))
    exit_code, payload = run_check(root)
    print(json.dumps(payload, indent=2))
    return exit_code


if __name__ == "__main__":
    run_module_main(main)
