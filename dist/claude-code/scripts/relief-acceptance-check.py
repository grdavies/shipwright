#!/usr/bin/env python3
"""Relief acceptance check — gates cutover on derived-vs-deliver alignment (PRD 031 R28). Usage: relief-acceptance-check.py [--repo-root ROOT] [--state PATH]"""
from __future__ import annotations

import sys

from _sw.cli import run_module_main


def main(argv: list[str] | None = None) -> int:
    import json
    import sys
    from pathlib import Path

    plugin_root, repo_root, state_path = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    sys.path.insert(0, str(plugin_root / "scripts"))
    import planning_index_gen as pig
    import planning_paths

    worktree = planning_paths.git_root(repo_root)
    index_path = worktree / pig.index_rel(repo_root)
    if not index_path.is_file():
        print(json.dumps({"verdict": "fail", "error": "planning INDEX missing"}))
        sys.exit(20)

    regions = pig.parse_regions(index_path.read_text(encoding="utf-8"))
    derived = pig.parse_derived_status_map(regions.derived)

    state_file = Path(state_path) if state_path else worktree / ".cursor/sw-deliver-state.json"
    deliver_status = {}
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
        sys.exit(20)

    print(json.dumps({
        "verdict": "pass",
        "action": "relief-acceptance-check",
        "derivedCount": len(derived),
        "deliverPhases": len(deliver_status),
    }))
    return 0


if __name__ == "__main__":
    run_module_main(main)
