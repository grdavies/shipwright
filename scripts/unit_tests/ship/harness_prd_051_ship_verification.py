#!/usr/bin/env python3
"""PRD 051 phase 3 — manifest registration + gap verification fixtures."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
_SCRIPTS_ROOT = SCRIPT_DIR.parents[1]
_TEST_DIR = _SCRIPTS_ROOT / "test"
for _entry in (str(_TEST_DIR), str(_SCRIPTS_ROOT)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from _sw.vendor_paths import repo_root

FAIL = 0


def _gap_backlog_text(root: Path) -> str:
    path = root / "docs/prds/GAP-BACKLOG.md"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _issue_store_cutover(root: Path) -> bool:
    """Issue-backed planning: legacy projection, local INDEX, or cutover gate."""
    backlog = _gap_backlog_text(root)
    if backlog and "planning-legacy-projection" in backlog[:400]:
        return True
    index = root / "docs/planning/INDEX.md"
    if index.is_file():
        try:
            if "planning-index:structural" in index.read_text(encoding="utf-8"):
                return True
        except OSError:
            pass
    gate = root / ".cursor/hooks/state/planning-cutover-gate.json"
    if not gate.is_file():
        return False
    try:
        return json.loads(gate.read_text(encoding="utf-8")).get("discoverSource") == "issue"
    except json.JSONDecodeError:
        return False


REQUIRED_SCENARIOS: dict[str, str] = {
    "spec-rigor-brainstorm-profile-required-sections": "spec-rigor-brainstorm-profile-fixtures",
    "stdlib-coverage-mode-no-behavior-change": "stdlib-coverage-fixtures",
    "stdlib-coverage-report-executed-and-unexecuted-lines": "stdlib-coverage-fixtures",
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
    by_id = {row["id"]: row for row in manifest.get("fixtures") or []}

    for scenario, suite_id in REQUIRED_SCENARIOS.items():
        row = by_id.get(suite_id)
        if not row or row.get("classification") != "required":
            bad(f"manifest-registration: {scenario} missing required entry for {suite_id}")
            continue
        scenarios = row.get("scenarios") or []
        if scenario not in scenarios:
            bad(f"manifest-registration: scenario {scenario} not listed on {suite_id}")
        else:
            ok(f"manifest-registration: {scenario}")

    backlog = (root / "docs/prds/GAP-BACKLOG.md").read_text(encoding="utf-8")
    gap_unit = "gap-001-spec-rigor-check-sh-lacks-a-brainstorm-artifact-"
    if _issue_store_cutover(root):
        index_path = root / "docs/planning/INDEX.md"
        index = index_path.read_text(encoding="utf-8") if index_path.is_file() else ""
        backlog = _gap_backlog_text(root)
        index_ok = bool(
            index
            and re.search(
                rf"\|\s*{re.escape(gap_unit)}[^|]*\|\s*gap\s*\|[^|]*\|\s*resolved\s*\|",
                index,
                re.I,
            )
        )
        backlog_ok = bool(
            re.search(
                rf"\|\s*GAP-001\s*\|\s*resolved\s*\|\s*{re.escape(gap_unit)}",
                backlog,
                re.I,
            )
        )
        if index_ok or backlog_ok:
            ok("gap-flip-verification: gap-001 planning unit resolved")
        else:
            bad("gap-flip-verification: gap-001 not resolved in INDEX")
    else:
        if "| GAP-076 | resolved |" in backlog:
            ok("gap-flip-verification: GAP-076 resolved in GAP-BACKLOG")
        else:
            bad("gap-flip-verification: GAP-076 not resolved in GAP-BACKLOG")
        index = (root / "docs/prds/INDEX.md").read_text(encoding="utf-8")
        if gap_unit in index and "| resolved |" in index.split("gap-001")[1][:200]:
            ok("gap-flip-verification: gap-001 planning unit resolved in INDEX")
        else:
            bad("gap-flip-verification: gap-001 not resolved in INDEX")

    # PRD 057 R5: these subprocess calls run against this repo's real root (not an isolated
    # fixture); this repo's committed backend is issue-store, so the cutover-gate default now
    # correctly routes discovery there — but this check exercises frontmatter-only reconciler
    # invariants, not live issue-store reachability/tokens. Pin "file" explicitly.
    subprocess_env = {**os.environ, "SW_DISCOVER_SOURCE": "file"}
    proc = subprocess.run(
        [sys.executable, str(root / "scripts/gap_backlog.py"), "check"],
        cwd=str(root),
        capture_output=True,
        text=True,
        env=subprocess_env,
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
        env=subprocess_env,
    )
    if proc2.returncode == 0:
        ok("gap-flip-verification: planning-graph reconcile dry-run passes")
    else:
        bad(f"gap-flip-verification: planning-graph reconcile failed: {proc2.stderr or proc2.stdout}")

    return FAIL


if __name__ == "__main__":
    raise SystemExit(main())
