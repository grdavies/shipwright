#!/usr/bin/env python3
"""PRD 046 phase-3 fixtures — hierarchy, recall, tracking issue (R23, R89-R91, R94)."""
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
export PYTHONPATH="$ROOT/scripts:${PYTHONPATH:-}"
HIER="$ROOT/scripts/planning_hierarchy.py"
RECALL="$ROOT/scripts/planning_cross_project_recall.py"
TRACK="$ROOT/scripts/planning_tracking_issue.py"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
(
  cd "$TMP"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  mkdir -p docs/prds/046-test .cursor/hooks/state
  echo ".cursor/hooks/state/" >> .gitignore
  git add .gitignore && git commit -q -m init
  cat > docs/prds/046-test/tasks-046-test.md <<'TASKS'
---
frozen: true
topic: 046-test
---
### 1. Alpha phase
### 2. Beta phase
TASKS
  cat > .cursor/workflow.config.json <<'CFG'
{"version":1,"planning":{"store":{"backend":"issue-store","issuesProvider":"github-issues","projectKey":"phase3046"}},"host":{"provider":"github"}}
CFG
  export SW_ISSUES_FIXTURE=1
  OUT=$(python3 "$HIER" --root "$TMP" project docs/prds/046-test/tasks-046-test.md)
  echo "$OUT" | grep -q '"mode": "epic-sub-issue"'
  echo "$OUT" | grep -q '"dryRun": true'
  echo "$OUT" | grep -q '"phaseCount": 2'
) && ok "epic-sub-issue-dry-run-github" || bad "epic-sub-issue-dry-run-github"

(
  cd "$TMP"
  python3 -c "import json; from pathlib import Path; p=Path('.cursor/workflow.config.json'); d=json.loads(p.read_text()); d['planning']['store']['issuesProvider']='none'; p.write_text(json.dumps(d))"
  OUT=$(python3 "$HIER" --root "$TMP" project docs/prds/046-test/tasks-046-test.md)
  echo "$OUT" | grep -q '"mode": "checkbox"'
  echo "$OUT" | grep -q 'Phase checklist'
) && ok "checkbox-fallback-provider-none" || bad "checkbox-fallback-provider-none"

(
  python3 -c "
import sys
sys.path.insert(0,'$ROOT/scripts')
import planning_hierarchy as ph
ok = ph.aggregate_parent_status(
    {'labels':['sw:tier:high','sw:status:proposed'],'state':'open'},
    [{'labels':['sw:tier:high','sw:status:proposed'],'state':'closed'},{'labels':['sw:tier:high','sw:status:proposed'],'state':'closed'}],
)
assert ok['verdict']=='ok' and ok['aggregated']['state']=='closed'
bad = ph.aggregate_parent_status(
    {'labels':['sw:tier:high'],'state':'open'},
    [{'labels':['sw:tier:low'],'state':'open'},{'labels':['sw:tier:high'],'state':'open'}],
)
assert bad['verdict']=='fail' and bad.get('failClosed')
"
) && ok "aggregate-parent-status-ok-and-conflict" || bad "aggregate-parent-status-ok-and-conflict"

(
  PAYLOAD=$(python3 -c "import json; print(json.dumps({'sourceProjectKey':'proj-a','callerProjectKey':'proj-b','query':'secret','pointers':[{'projectKey':'proj-a','unitId':'u1','memoryId':'m1','visibility':'private','excerpt':'Secret rationale text'}],'authorizedProjects':['proj-a']}))")
  OUT=$(python3 "$RECALL" --root "$TMP" recall --payload-json "$PAYLOAD")
  echo "$OUT" | grep -q 'u1: \[private\]'
  ! echo "$OUT" | grep -q 'Secret rationale'
) && ok "cross-project-recall-private-opaque" || bad "cross-project-recall-private-opaque"

(
  cd "$TMP"
  export SW_VISIBILITY_REMOTE_PROBE=public
  PAYLOAD=$(python3 -c "import json; print(json.dumps({'unitId':'prd-private','tuple':{'runId':'run-1','epoch':1,'branch':'feat/secret'},'visibility':'private'}))")
  OUT=$(python3 "$TRACK" --root "$TMP" prepare --payload-json "$PAYLOAD")
  echo "$OUT" | grep -q '"verdict": "refused"'
  echo "$OUT" | grep -q 'private-tracking-on-public-store'
  unset SW_VISIBILITY_REMOTE_PROBE
) && ok "tracking-issue-refused-private-public-store" || bad "tracking-issue-refused-private-public-store"

exit "$FAIL"
"""

if __name__ == "__main__":
    raise SystemExit(main())
