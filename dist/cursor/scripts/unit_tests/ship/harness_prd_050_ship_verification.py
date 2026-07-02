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

from _fixture_lib import repo_root

FAIL = 0

REQUIRED_SCENARIOS: dict[str, str] = {
    "freeze-commit-cwd-forced-primary-fails-closed": "scripts/test/run_deliver_concurrency_fixtures.py",
    "deliver-provision-does-not-mutate-concurrent-primary-checkout": "scripts/test/run_deliver_concurrency_fixtures.py",
    "slug-scoped-run-log-writes": "scripts/test/run_deliver_concurrency_fixtures.py",
    "conductor-mandatory-provisioning-contract": "scripts/test/run_deliver_concurrency_fixtures.py",
    "orphan-phase-worktree-adopt-or-teardown": "scripts/test/run_deliver_concurrency_fixtures.py",
    "no-progress-differentiated-stall-causes": "scripts/test/run_deliver_concurrency_fixtures.py",
    "stale-in-progress-success-check-gate-green": "scripts/test/run_deliver_concurrency_fixtures.py",
    "finalize-resume-after-state-cleared-post-merge": "scripts/test/run_deliver_concurrency_fixtures.py",
    "terminal-pr-body-template-valid": "scripts/test/run_deliver_concurrency_fixtures.py",
    "finalize-living-docs-reconcile-hook": "scripts/test/run_deliver_concurrency_fixtures.py",
    "terminal-docs-currency-gate-invocation-valid": "scripts/test/run_deliver_concurrency_fixtures.py",
    "resume-reconcile-unpushed-local-merge-promotes": "scripts/test/run_deliver_concurrency_fixtures.py",
    "deliver-fail-payload-forwards-subprocess-error": "scripts/test/run_deliver_concurrency_fixtures.py",
    "deliver-verify-fixture-tree-immutable": "scripts/test/run_deliver_concurrency_fixtures.py",
    "capability-gateref-no-shell": "scripts/test/run_deliver_concurrency_fixtures.py",
    "all-private-spec-seed-tracked-private-body": "scripts/test/run_deliver_concurrency_fixtures.py",
    "hook-state-worktree-cwd-alignment": "scripts/test/run_hook_worktree_alignment_fixtures.py",
    "hook-state-dispatch-preflight-worktree-alignment": "scripts/test/run_hook_worktree_alignment_fixtures.py",
    "hook-state-primary-no-false-positive": "scripts/test/run_hook_worktree_alignment_fixtures.py",
    "hook-state-ambiguous-worktree-fail-closed": "scripts/test/run_hook_worktree_alignment_fixtures.py",
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


def _manifest_by_script(manifest: dict) -> dict[str, dict]:
    return {row["script"]: row for row in manifest.get("fixtures") or []}


def check_manifest_registration(root: Path) -> None:
    manifest = json.loads((root / "core/sw-reference/pr-test-plan.manifest.json").read_text(encoding="utf-8"))
    by_script = _manifest_by_script(manifest)
    for scenario, script in REQUIRED_SCENARIOS.items():
        row = by_script.get(script)
        if not row or row.get("classification") != "required":
            bad(f"manifest-registration: {scenario} missing required entry for {script}")
            continue
        scenarios = row.get("scenarios") or []
        if scenario not in scenarios:
            bad(f"manifest-registration: scenario {scenario} not listed on {row.get('id')}")
        else:
            ok(f"manifest-registration: {scenario}")


def check_legacy_gaps(root: Path) -> None:
    backlog = (root / "docs/prds/GAP-BACKLOG.md").read_text(encoding="utf-8")
    for gap_id in LEGACY_GAPS:
        if re.search(rf"\|\s*{re.escape(gap_id)}\s*\|\s*resolved\s*\|", backlog, re.I):
            ok(f"gap-flip-verification: {gap_id} resolved in GAP-BACKLOG")
        else:
            bad(f"gap-flip-verification: {gap_id} not resolved in GAP-BACKLOG")


def check_canonical_gaps(root: Path) -> None:
    index = (root / "docs/prds/INDEX.md").read_text(encoding="utf-8")
    for gap_prefix in CANONICAL_GAPS:
        pattern = rf"\|\s*{re.escape(gap_prefix)}[^|]*\|\s*gap\s*\|[^|]*\|\s*resolved\s*\|"
        if re.search(pattern, index, re.I):
            ok(f"gap-flip-verification: {gap_prefix} resolved in INDEX")
        else:
            bad(f"gap-flip-verification: {gap_prefix} not resolved in INDEX")


def check_feedback_gap(root: Path) -> None:
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
