#!/usr/bin/env python3
"""Relief acceptance check — gates cutover on derived-vs-deliver alignment (PRD 031 R28)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_index_gen as pig
import planning_paths
from _sw.cli import run_module_main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Relief acceptance check")
    parser.add_argument("--repo-root", type=Path, default=SCRIPT_DIR.parent)
    parser.add_argument("--state", type=Path, default=None)
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    worktree = planning_paths.git_root(repo_root)
    index_path = worktree / pig.index_rel(repo_root)
    if not index_path.is_file():
        print(json.dumps({"verdict": "fail", "error": "planning INDEX missing"}))
        return 20

    regions = pig.parse_regions(index_path.read_text(encoding="utf-8"))
    derived = pig.parse_derived_status_map(regions.derived)

    state_file = args.state if args.state else worktree / ".cursor/sw-deliver-state.json"
    deliver_status: dict[str, str] = {}
    if state_file.is_file():
        state = json.loads(state_file.read_text(encoding="utf-8"))
        for meta in (state.get("phases") or {}).values():
            slug = str((meta or {}).get("slug") or "")
            status = str((meta or {}).get("status") or "")
            if slug:
                deliver_status[slug] = status

    mismatches = []
    for unit_id, derived_status in derived.items():
        phase_slug = unit_id.replace("prd-", "", 1) if unit_id.startswith("prd-") else unit_id
        if phase_slug in deliver_status:
            mapped = "complete" if deliver_status[phase_slug] in ("green-merged", "merge-ready-green") else "in-progress"
            if derived_status != mapped:
                mismatches.append({"unit": unit_id, "derived": derived_status, "deliver": mapped})

    if mismatches:
        print(json.dumps({"verdict": "fail", "error": "relief acceptance mismatch", "mismatches": mismatches}))
        return 20

    print(json.dumps({
        "verdict": "pass",
        "action": "relief-acceptance-check",
        "derivedCount": len(derived),
        "deliverPhases": len(deliver_status),
    }))
    return 0


if __name__ == "__main__":
    run_module_main(main)
