#!/usr/bin/env python3
"""PRD 051 phase 3 — manifest registration + gap verification fixtures."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR.parent))

from _fixture_lib import repo_root

FAIL = 0

REQUIRED_FIXTURES = {
    "spec-rigor-brainstorm-profile-required-sections": "scripts/test/run_spec_rigor_brainstorm_profile_fixtures.py",
    "stdlib-coverage-mode-no-behavior-change": "scripts/test/run_stdlib_coverage_fixtures.py",
    "stdlib-coverage-report-executed-and-unexecuted-lines": "scripts/test/run_stdlib_coverage_fixtures.py",
}


def ok(msg: str) -> None:
    print(f"OK  {msg}")


def bad(msg: str) -> None:
    global FAIL
    print(f"FAIL {msg}")
    FAIL = 1


def main() -> int:
    root = repo_root(__file__)
    manifest = json.loads((root / "core/sw-reference/pr-test-plan.manifest.json").read_text(encoding="utf-8"))
    by_script = {row["script"]: row for row in manifest.get("fixtures") or []}

    for scenario, script in REQUIRED_FIXTURES.items():
        row = by_script.get(script)
        if not row or row.get("classification") != "required":
            bad(f"manifest-registration: {scenario} missing required entry for {script}")
            continue
        scenarios = row.get("scenarios") or []
        if scenario not in scenarios:
            bad(f"manifest-registration: scenario {scenario} not listed on {row.get('id')}")
        else:
            ok(f"manifest-registration: {scenario}")

    backlog = (root / "docs/prds/GAP-BACKLOG.md").read_text(encoding="utf-8")
    if "| GAP-076 | resolved |" in backlog:
        ok("gap-flip-verification: GAP-076 resolved in GAP-BACKLOG")
    else:
        bad("gap-flip-verification: GAP-076 not resolved in GAP-BACKLOG")

    index = (root / "docs/prds/INDEX.md").read_text(encoding="utf-8")
    if "gap-001-spec-rigor-check-sh-lacks-a-brainstorm-artifact-" in index and "| resolved |" in index.split("gap-001")[1][:200]:
        ok("gap-flip-verification: gap-001 planning unit resolved in INDEX")
    else:
        bad("gap-flip-verification: gap-001 not resolved in INDEX")

    proc = subprocess.run(
        [sys.executable, str(root / "scripts/gap_backlog.py"), "check"],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        ok("gap-flip-verification: gap_backlog.py check passes")
    else:
        bad(f"gap-flip-verification: gap_backlog check failed: {proc.stdout}")

    proc2 = subprocess.run(
        [sys.executable, str(root / "scripts/planning-graph.py"), "reconcile", "--dry-run"],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    if proc2.returncode == 0:
        ok("gap-flip-verification: planning-graph reconcile dry-run passes")
    else:
        bad(f"gap-flip-verification: planning-graph reconcile failed: {proc2.stderr or proc2.stdout}")

    return FAIL


if __name__ == "__main__":
    raise SystemExit(main())
