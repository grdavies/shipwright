#!/usr/bin/env python3
"""PRD 045 phase 1 — doc-impact acceptance (R49) + gap-issue projection contract."""
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
    completed = subprocess.run(
        ["bash", "-c", src],
        cwd=str(root),
        env=env,
        shell=False,
    )
    return completed.returncode


_SOURCE = r"""
#!/usr/bin/env bash
# PRD 045 phase 1 — doc-impact acceptance (R49).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=scripts/test/fixture-lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/fixture-lib.sh"

FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

FEEDBACK="$(content_path skills/feedback/SKILL.md)"
FEEDBACK_CLOSE="$(content_path skills/feedback-closure/SKILL.md)"
LIVING="$(content_path skills/living-status/SKILL.md)"
LAYOUT="$ROOT/.sw/layout.md"
EMIT="$(content_path skills/visibility/references/emission-points.md)"
GAP_CAPTURE="$ROOT/scripts/planning_gap_capture.py"
MIGRATE="$ROOT/scripts/planning_migrate_issue_store.py"

check() {
  local name="$1" file="$2" pattern="$3"
  if grep -qE "$pattern" "$file" 2>/dev/null; then ok "$name"; else bad "$name"; fi
}

check "doc-currency-045:feedback-sw-gap" "$FEEDBACK" "sw:gap"
check "doc-currency-045:feedback-gap-labels" "$FEEDBACK" "gap-scheduled"
check "doc-currency-045:feedback-issue-store" "$FEEDBACK" "issue-store"
check "doc-currency-045:feedback-write-through" "$FEEDBACK" "write-through"
check "doc-currency-045:feedback-closure-projection" "$FEEDBACK_CLOSE" "write-through"
check "doc-currency-045:feedback-closure-doctor" "$FEEDBACK_CLOSE" "planning-graph doctor"
check "doc-currency-045:living-status-labels" "$LIVING" "gap-scheduled"
check "doc-currency-045:living-status-doctor" "$LIVING" "planning-graph doctor"
check "doc-currency-045:layout-write-through" "$LAYOUT" "write-through"
check "doc-currency-045:emission-gap-backlog" "$EMIT" "issue-derived write-through"

# Behavioral: issue-store gap capture + projection refresh (R21/R72)
export SW_ISSUES_FIXTURE=1
WF_BACKUP=""
if [[ -f "$ROOT/.cursor/workflow.config.json" ]]; then
  WF_BACKUP="$(mktemp)"
  cp "$ROOT/.cursor/workflow.config.json" "$WF_BACKUP"
fi
python3 - <<PY
import json
from pathlib import Path
cfg = {
  "version": 1,
  "planning": {
    "store": {
      "backend": "issue-store",
      "issuesProvider": "github-issues",
      "projectKey": "fixture-gap-045",
    }
  },
}
Path("$ROOT/.cursor/workflow.config.json").write_text(json.dumps(cfg, indent=2) + "\\n", encoding="utf-8")
PY
python3 "$ROOT/scripts/planning_store.py" --root "$ROOT" clear-issue-fixture >/dev/null
GAP_BACKLOG="$ROOT/docs/prds/GAP-BACKLOG.md"
GAP_BACKUP=""
if [[ -f "$GAP_BACKLOG" ]]; then
  GAP_BACKUP="$(mktemp)"
  cp "$GAP_BACKLOG" "$GAP_BACKUP"
  rm -f "$GAP_BACKLOG"
fi
restore_fixtures() {
  if [[ -n "$WF_BACKUP" ]]; then
    cp "$WF_BACKUP" "$ROOT/.cursor/workflow.config.json"
    rm -f "$WF_BACKUP"
  fi
  if [[ -n "$GAP_BACKUP" ]]; then
    cp "$GAP_BACKUP" "$GAP_BACKLOG"
    rm -f "$GAP_BACKUP"
  elif [[ -f "$GAP_BACKLOG" ]]; then
    rm -f "$GAP_BACKLOG"
  fi
  python3 "$ROOT/scripts/planning_store.py" --root "$ROOT" clear-issue-fixture >/dev/null || true
}
trap 'restore_fixtures' EXIT
if python3 "$GAP_CAPTURE" "$ROOT" capture --signal-id fb-045-001 --title "Fixture gap projection" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('verdict')=='pass'
assert d.get('action')=='gap-capture'
"; then
  ok "gap-capture-issue-store"
else
  bad "gap-capture-issue-store"
fi
if [[ -f "$GAP_BACKLOG" ]] && grep -qE '\| GAP-[0-9]+ \|' "$GAP_BACKLOG"; then
  ok "gap-backlog-write-through"
else
  bad "gap-backlog-write-through"
fi
if python3 "$ROOT/scripts/planning_graph.py" "$ROOT" doctor | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('verdict')=='pass'
"; then
  ok "gap-projection-doctor-pass"
else
  bad "gap-projection-doctor-pass"
fi
# Divergence should fail closed
python3 "$GAP_CAPTURE" "$ROOT" refresh-projection >/dev/null
echo "| GAP-999 | resolved | stale title |" >> "$GAP_BACKLOG"
if python3 "$ROOT/scripts/planning_graph.py" "$ROOT" doctor 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('verdict')=='fail'
assert d.get('halt')=='gap-projection-divergence'
"; then
  ok "gap-projection-doctor-divergence"
else
  bad "gap-projection-doctor-divergence"
fi
restore_fixtures
trap - EXIT

[[ "$FAIL" -eq 0 ]] && ok "doc-currency-045"
exit "$FAIL"
"""

if __name__ == "__main__":
    raise SystemExit(main())
