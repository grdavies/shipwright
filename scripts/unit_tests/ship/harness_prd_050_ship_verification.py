#!/usr/bin/env python3
"""PRD 050 phase 5 — manifest registration + gap verification fixtures."""
from __future__ import annotations

import json
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


def _issue_store_cutover(root: Path) -> bool:
    gate = root / ".cursor/hooks/state/planning-cutover-gate.json"
    if not gate.is_file():
        return False
    try:
        return json.loads(gate.read_text(encoding="utf-8")).get("discoverSource") == "issue"
    except json.JSONDecodeError:
        return False


def _planning_index_text(root: Path) -> str:
    path = root / "docs/planning/INDEX.md"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


REQUIRED_SCENARIOS: dict[str, str] = {
    "freeze-commit-cwd-forced-primary-fails-closed": "deliver-concurrency-fixtures",
    "deliver-provision-does-not-mutate-concurrent-primary-checkout": "deliver-concurrency-fixtures",
    "slug-scoped-run-log-writes": "deliver-concurrency-fixtures",
    "conductor-mandatory-provisioning-contract": "deliver-concurrency-fixtures",
    "orphan-phase-worktree-adopt-or-teardown": "deliver-concurrency-fixtures",
    "no-progress-differentiated-stall-causes": "deliver-concurrency-fixtures",
    "stale-in-progress-success-check-gate-green": "deliver-concurrency-fixtures",
    "finalize-resume-after-state-cleared-post-merge": "deliver-concurrency-fixtures",
    "terminal-pr-body-template-valid": "deliver-concurrency-fixtures",
    "finalize-living-docs-reconcile-hook": "deliver-concurrency-fixtures",
    "terminal-docs-currency-gate-invocation-valid": "deliver-concurrency-fixtures",
    "resume-reconcile-unpushed-local-merge-promotes": "deliver-concurrency-fixtures",
    "deliver-fail-payload-forwards-subprocess-error": "deliver-concurrency-fixtures",
    "deliver-verify-fixture-tree-immutable": "deliver-concurrency-fixtures",
    "capability-gateref-no-shell": "deliver-concurrency-fixtures",
    "all-private-spec-seed-tracked-private-body": "deliver-concurrency-fixtures",
    "hook-state-worktree-cwd-alignment": "hook-worktree-alignment-fixtures",
    "hook-state-dispatch-preflight-worktree-alignment": "hook-worktree-alignment-fixtures",
    "hook-state-primary-no-false-positive": "hook-worktree-alignment-fixtures",
    "hook-state-ambiguous-worktree-fail-closed": "hook-worktree-alignment-fixtures",
}

LEGACY_GAPS = ("GAP-077", "GAP-078", "GAP-079", "GAP-080")
CANONICAL_GAPS = (
    "gap-005-freeze-commit-spec-seed-cwd-dependent-repo-root-",
    "gap-009-failed-phase-provision-leaves-orphan-worktree-wi",
    "gap-010-durable-deliver-state-loss-blocks-finalize-compl",
    "gap-011-conductor-no-progress-regression-on-provision-an",
    "gap-012-stale-github-check-in-progress-blocks-stuck-stal",
    "gap-013-terminal-pr-prepare-body-skips-template-validati",
    "gap-014-capability-trust-fixtures-regress-to-check-gate-",
    "gap-015-all-private-profile-requires-visibility-public-a",
)

FEEDBACK_GAP_ID = "feedback-hook-worktree-root-mismatch-2026-07-01"


def ok(msg: str) -> None:
    print(f"OK  {msg}")


def bad(msg: str) -> None:
    global FAIL
    print(f"FAIL {msg}")
    FAIL = 1


def _manifest_by_id(manifest: dict) -> dict[str, dict]:
    return {row["id"]: row for row in manifest.get("fixtures") or []}


def check_manifest_registration(root: Path) -> None:
    manifest = json.loads((root / "core/sw-reference/pr-test-plan.manifest.json").read_text(encoding="utf-8"))
    by_id = _manifest_by_id(manifest)
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


def check_legacy_gaps(root: Path) -> None:
    if _issue_store_cutover(root):
        log = (root / "docs/prds/COMPLETION-LOG.md").read_text(encoding="utf-8")
        if re.search(r"\|\s*050\s*\|", log):
            ok("gap-flip-verification: PRD 050 complete per COMPLETION-LOG")
        else:
            bad("gap-flip-verification: PRD 050 not recorded in COMPLETION-LOG")
        return
    backlog = (root / "docs/prds/GAP-BACKLOG.md").read_text(encoding="utf-8")
    for gap_id in LEGACY_GAPS:
        if re.search(rf"\|\s*{re.escape(gap_id)}\s*\|\s*resolved\s*\|", backlog, re.I):
            ok(f"gap-flip-verification: {gap_id} resolved in GAP-BACKLOG")
        else:
            bad(f"gap-flip-verification: {gap_id} not resolved in GAP-BACKLOG")


def check_canonical_gaps(root: Path) -> None:
    if _issue_store_cutover(root):
        index = _planning_index_text(root)
    else:
        index = (root / "docs/prds/INDEX.md").read_text(encoding="utf-8")
    for gap_prefix in CANONICAL_GAPS:
        pattern = rf"\|\s*{re.escape(gap_prefix)}[^|]*\|\s*gap\s*\|[^|]*\|\s*resolved\s*\|"
        if re.search(pattern, index, re.I):
            ok(f"gap-flip-verification: {gap_prefix} resolved in INDEX")
        else:
            bad(f"gap-flip-verification: {gap_prefix} not resolved in INDEX")


def check_feedback_gap(root: Path) -> None:
    if _issue_store_cutover(root):
        index = _planning_index_text(root)
        backlog = (root / "docs/prds/GAP-BACKLOG.md").read_text(encoding="utf-8")
        if re.search(
            rf"\|\s*{re.escape(FEEDBACK_GAP_ID)}[^|]*\|\s*gap\s*\|[^|]*\|\s*resolved\s*\|",
            index,
            re.I,
        ):
            ok(f"feedback-signal-gap-flip: {FEEDBACK_GAP_ID} status resolved")
        elif re.search(
            rf"\|\s*FEEDBACK-HOOK-WORKTREE-ROOT-MISMATCH-2026-07-01\s*\|\s*resolved\s*\|",
            backlog,
            re.I,
        ):
            ok(f"feedback-signal-gap-flip: {FEEDBACK_GAP_ID} resolved in GAP-BACKLOG")
        else:
            bad(f"feedback-signal-gap-flip: {FEEDBACK_GAP_ID} not resolved in planning INDEX")
        return
    gap_dir = root / "docs/prds/gap"
    matches = sorted(gap_dir.glob(f"*{FEEDBACK_GAP_ID}*/*.md"))
    if not matches:
        bad(f"feedback-signal-gap-flip: gap unit for {FEEDBACK_GAP_ID} not found")
        return
    text = matches[0].read_text(encoding="utf-8")
    if re.search(r"^status:\s*resolved\s*$", text, re.M | re.I):
        ok(f"feedback-signal-gap-flip: {FEEDBACK_GAP_ID} status resolved")
    else:
        bad(f"feedback-signal-gap-flip: {FEEDBACK_GAP_ID} not resolved")
    if "PRD 050 A1" in text or "resolvedBy: PRD 050 A1" in text:
        ok("feedback-signal-gap-flip: resolvedBy references PRD 050 A1")
    else:
        bad("feedback-signal-gap-flip: missing PRD 050 A1 resolvedBy reference")


def main() -> int:
    root = repo_root(__file__)
    check_manifest_registration(root)
    check_legacy_gaps(root)
    check_canonical_gaps(root)
    check_feedback_gap(root)

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

    return FAIL


if __name__ == "__main__":
    raise SystemExit(main())
