#!/usr/bin/env python3
"""PRD 046 phase-1 doc-impact gate (R49)."""
from __future__ import annotations

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
from unit_tests._harness_runtime import harness_subprocess_env as _harness_env
from unit_tests._harness_runtime import patch_source as _patch_source


def main() -> int:
    root = repo_root(__file__)
    env = _harness_env(root)
    src = _patch_source(_SOURCE, root)
    completed = subprocess.run(["bash", "-c", src], cwd=str(root), env=env, shell=False)
    return completed.returncode


_SOURCE = r"""
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$ROOT/scripts/test/fixture-lib.sh"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }
check() { local n="$1" f="$2" p="$3"; if grep -qE "$p" "$f" 2>/dev/null; then ok "$n"; else bad "$n"; fi; }

LAYOUT="$ROOT/.sw/layout.md"
SHIP_STATE="$(content_path skills/shipwright-state/SKILL.md)"
ISSUE_STORE="$(content_path providers/planning-store/issue-store.md)"
DELIVER="$(content_path skills/deliver/SKILL.md)"
CONDUCTOR="$(content_path skills/conductor/SKILL.md)"

check "doc-currency-046:layout-dual-mode-index" "$LAYOUT" "Issue-store region disposition"
check "doc-currency-046:layout-mechanical-region" "$LAYOUT" "never mechanically edited"
check "doc-currency-046:layout-inflight-projection" "$LAYOUT" "deliver writer"
check "doc-currency-046:ship-state-phase-runs" "$SHIP_STATE" "sw-deliver-runs"
check "doc-currency-046:issue-store-discover" "$ISSUE_STORE" "discover_units"
check "doc-currency-046:deliver-inflight-projection" "$DELIVER" "inFlight"
check "doc-currency-046:conductor-cutover" "$ROOT/scripts/planning_cutover.py" "doctor"
CONFIG_GUIDE="$ROOT/docs/guides/configuration.md"
check "doc-currency-046:configuration-request-budget" "$CONFIG_GUIDE" "requestBudget"
check "doc-currency-046:issue-store-cache-ttl" "$ISSUE_STORE" "cacheTtlSeconds"
check "doc-currency-046:sw-deliver-scheduler" "$(content_path commands/sw-deliver.md)" "schedule-next"
check "doc-currency-046:emission-issue-derived-ingest" "$ROOT/core/skills/visibility/references/emission-points.md" "issue-derived-ingest"
[[ -f "$ROOT/scripts/planning_request_budget.py" ]] && ok "doc-currency-046:request-budget-present" || bad "doc-currency-046:request-budget-present"
[[ -f "$ROOT/scripts/planning_query_cache.py" ]] && ok "doc-currency-046:query-cache-present" || bad "doc-currency-046:query-cache-present"
[[ -f "$ROOT/scripts/planning_scheduler.py" ]] && ok "doc-currency-046:scheduler-present" || bad "doc-currency-046:scheduler-present"

[[ -f "$ROOT/scripts/planning_discover.py" ]] && ok "doc-currency-046:planning-discover-present" || bad "doc-currency-046:planning-discover-present"
[[ -f "$ROOT/scripts/planning_region_disposition.py" ]] && ok "doc-currency-046:region-disposition-present" || bad "doc-currency-046:region-disposition-present"


WORKFLOWS="$ROOT/docs/guides/workflows.md"
README="$ROOT/README.md"
MEMORY_SKILL="$(content_path skills/memory/SKILL.md)"
RECALLIUM="$(content_path providers/recallium.md)"
check "doc-currency-046:workflows-hierarchy" "$WORKFLOWS" "epic/sub-issue"
check "doc-currency-046:workflows-recall" "$WORKFLOWS" "cross-project recall"
check "doc-currency-046:workflows-tracking" "$WORKFLOWS" "tracking-issue"
check "doc-currency-046:readme-issue-graph" "$README" "issue-derived planning graph"
check "doc-currency-046:memory-cross-project-recall" "$MEMORY_SKILL" "Cross-project recall"
check "doc-currency-046:recallium-cross-project" "$RECALLIUM" "Cross-project recall"
check "doc-currency-046:deliver-hierarchy" "$DELIVER" "Task-list hierarchy"
check "doc-currency-046:issues-capabilities-hierarchy" "$(content_path providers/issues/CAPABILITIES.md)" "issue-epic-create"
[[ -f "$ROOT/scripts/planning_hierarchy.py" ]] && ok "doc-currency-046:planning-hierarchy-present" || bad "doc-currency-046:planning-hierarchy-present"
[[ -f "$ROOT/scripts/planning_tracking_issue.py" ]] && ok "doc-currency-046:planning-tracking-issue-present" || bad "doc-currency-046:planning-tracking-issue-present"
[[ -f "$ROOT/scripts/planning_cross_project_recall.py" ]] && ok "doc-currency-046:cross-project-recall-present" || bad "doc-currency-046:cross-project-recall-present"

exit "$FAIL"
"""

if __name__ == "__main__":
    raise SystemExit(main())
