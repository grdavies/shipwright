#!/usr/bin/env python3
"""PRD 045 — doc-impact acceptance (R49) + gap-issue projection + phase-2 linkage + phase-3 doc-review/milestones."""
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
# PRD 045 — doc-impact acceptance (R49): phase 1 gap issues + phase 2 linkage/close/annotations + phase 3 doc-review/milestones.
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
GIT_WF="$(content_path skills/git-workflow/SKILL.md)"
SW_COMMIT="$(content_path commands/sw-commit.md)"
SW_PR="$(content_path commands/sw-pr.md)"
SW_SHIP="$(content_path commands/sw-ship.md)"
DELIVER="$(content_path skills/deliver/SKILL.md)"
SHIP_STATE="$(content_path skills/shipwright-state/SKILL.md)"
ISSUES_CAP="$(content_path providers/issues/CAPABILITIES.md)"
CAP_INDEX="$ROOT/core/sw-reference/capability-index.json"

check() {
  local name="$1" file="$2" pattern="$3"
  if grep -qE "$pattern" "$file" 2>/dev/null; then ok "$name"; else bad "$name"; fi
}

# --- Phase 1 (gap issues + write-through) ---
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

# --- Phase 2 (linkage, safe close, deliver annotations) ---
check "doc-currency-045-p2:git-workflow-linkage" "$GIT_WF" "Planning-issue linkage"
check "doc-currency-045-p2:git-workflow-location-mode" "$GIT_WF" "same-repo"
check "doc-currency-045-p2:git-workflow-deliver-annotate" "$GIT_WF" "sw:deliver-annotate"
check "doc-currency-045-p2:sw-commit-planning-issues" "$SW_COMMIT" "Planning-Issues:"
check "doc-currency-045-p2:sw-pr-linked-planning" "$SW_PR" "Linked planning issues"
check "doc-currency-045-p2:sw-pr-unlinked-closes" "$SW_PR" "unlinked.*Closes"
check "doc-currency-045-p2:sw-ship-annotate-close" "$SW_SHIP" "issue-batch annotate"
check "doc-currency-045-p2:sw-ship-allowlist" "$SW_SHIP" "sw:deliver-link"
check "doc-currency-045-p2:deliver-annotation-batch" "$DELIVER" "sw:deliver-annotate"
check "doc-currency-045-p2:deliver-safe-close" "$DELIVER" "close-on-merge"
check "doc-currency-045-p2:deliver-issue-batch-journal" "$DELIVER" "issue-batch-journal"
check "doc-currency-045-p2:deliver-aborted-inconsistent" "$DELIVER" "deliver-aborted-inconsistent"
check "doc-currency-045-p2:deliver-upsert-marker" "$DELIVER" "upsert-by-marker"
check "doc-currency-045-p2:deliver-linkage-sot" "$DELIVER" "verify-only"
check "doc-currency-045-p2:deliver-redaction" "$DELIVER" "deliver-annotation-ingest"
check "doc-currency-045-p2:ship-state-journal" "$SHIP_STATE" "deliverIssueBatch"
check "doc-currency-045-p2:emission-deliver-annotation" "$EMIT" "deliver-annotation"
check "doc-currency-045-p2:emission-issue-close" "$EMIT" "issue-close-batch"
check "doc-currency-045-p2:issues-cap-close" "$ISSUES_CAP" "issue-close"
check "doc-currency-045-p2:issues-cap-linked-pr" "$ISSUES_CAP" "linked-pr-introspection"
check "doc-currency-045-p2:cap-index-linkage-sot" "$CAP_INDEX" "linkageSoT"

# --- Phase 3 (doc-review via comments + milestones) ---
SW_DOC_REVIEW="$(content_path commands/sw-doc-review.md)"
DOC_REVIEW="$(content_path skills/doc-review/SKILL.md)"
SYNTHESIS="$(content_path skills/doc-review/references/synthesis.md)"
CONFIG_SCHEMA="$ROOT/.sw/config.schema.json"
CONFIG_GUIDE="$ROOT/docs/guides/configuration.md"
WORKFLOWS="$ROOT/docs/guides/workflows.md"
README="$ROOT/README.md"
GETTING_STARTED="$ROOT/docs/guides/getting-started.md"

check "doc-currency-045-p3:sw-doc-review-issue-store" "$SW_DOC_REVIEW" "issue-store"
check "doc-currency-045-p3:sw-doc-review-ide-fallback" "$SW_DOC_REVIEW" "IDE panel"
check "doc-currency-045-p3:doc-review-transport" "$DOC_REVIEW" "sw:doc-review"
check "doc-currency-045-p3:doc-review-manifest" "$DOC_REVIEW" "review-round manifest"
check "doc-currency-045-p3:doc-review-canonicalization-exclude" "$DOC_REVIEW" "excluded.*R35"
check "doc-currency-045-p3:synthesis-manifest" "$SYNTHESIS" "review-round manifest"
check "doc-currency-045-p3:synthesis-fail-closed" "$SYNTHESIS" "fail closed"
check "doc-currency-045-p3:config-release-grouping" "$CONFIG_SCHEMA" "releaseGrouping"
check "doc-currency-045-p3:config-milestone-mode" "$CONFIG_SCHEMA" "milestone"
check "doc-currency-045-p3:guide-release-grouping" "$CONFIG_GUIDE" "issue-milestone"
check "doc-currency-045-p3:guide-skip-notice" "$CONFIG_GUIDE" "skip with operator"
check "doc-currency-045-p3:issues-cap-milestone" "$ISSUES_CAP" "issue-milestone"
check "doc-currency-045-p3:issues-cap-milestone-degrade" "$ISSUES_CAP" "skip with operator"
check "doc-currency-045-p3:cap-index-milestone-verb" "$CAP_INDEX" "issueMilestoneVerb"
check "doc-currency-045-p3:workflows-doc-review" "$WORKFLOWS" "sw:doc-review"
check "doc-currency-045-p3:workflows-milestone" "$WORKFLOWS" "issue-milestone"
check "doc-currency-045-p3:readme-dev-tracking" "$README" "issue-native dev-tracking"
check "doc-currency-045-p3:getting-started-issue-store" "$GETTING_STARTED" "issue-store"

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
