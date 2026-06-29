#!/usr/bin/env bash
# PRD 033 phase 7 — operator doc acceptance fixtures (R25).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=scripts/test/fixture-lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/fixture-lib.sh"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

LIVING="$(content_path skills/living-status/SKILL.md)"
DELIVER="$(content_path commands/sw-deliver.md)"
STATUS="$(content_path commands/sw-status.md)"
WF="$ROOT/docs/guides/workflows.md"
GS="$ROOT/docs/guides/getting-started.md"

check() {
  local name="$1" file="$2" pattern="$3"
  if grep -q "$pattern" "$file" 2>/dev/null; then ok "$name"; else bad "$name"; fi
}

# doc-currency-033-sections (living-status + commands)
check "living-status-reconciler" "$LIVING" "planning-graph reconcile"
check "living-status-inflight" "$LIVING" "inFlight"
check "living-status-archive" "$LIVING" "INDEX-archive"
check "living-status-gap-units" "$LIVING" "planning_gap_capture"
check "sw-deliver-next" "$DELIVER" "wave_deliver.py.*next"
check "sw-deliver-dependency-gate" "$DELIVER" "dependency-gate"
check "sw-deliver-soft-enforce" "$DELIVER" "planning.autonomy"
check "sw-deliver-run-start" "$DELIVER" "Run-start"
check "sw-status-gap-echo" "$STATUS" "planning/INDEX"
check "sw-status-override-drift" "$STATUS" "override drift"

# doc-currency-033-sections (guides)
check "workflows-lifecycle" "$WF" "Planning lifecycle (PRD 033)"
check "workflows-deliver-next" "$WF" "/sw-deliver next"
check "workflows-reconciler" "$WF" "planning-graph reconcile"
check "workflows-legacy-projection" "$WF" "read-only projection"
check "getting-started-reconciler" "$GS" "maintenance reconciler"
check "getting-started-planning-index" "$GS" "docs/planning/INDEX"

exit "$FAIL"
