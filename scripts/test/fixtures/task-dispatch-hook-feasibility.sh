#!/usr/bin/env bash
# Feasibility spike + logic tests for before_task_dispatch (PRD 012 phase 4 / DL-2).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
FEAS="$ROOT/core/sw-reference/model-tier-hook-feasibility.md"
HOOKS_JSON="$ROOT/dist/cursor/hooks/hooks.json"
PY="$ROOT/core/hooks/before_task_dispatch.py"

FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

if [[ ! -f "$FEAS" ]]; then
  bad "model-tier-hook-feasibility.md present"
else
  ok "model-tier-hook-feasibility.md present"
  if grep -q "Deferred" "$FEAS" && grep -q "subagentStart" "$FEAS"; then
    ok "feasibility-doc-deferred-verdict"
  else
    bad "feasibility-doc-deferred-verdict"
  fi
fi

if [[ ! -f "$PY" ]]; then
  bad "before_task_dispatch.py present"
else
  ok "before_task_dispatch.py present"
fi

# Logic: reviewer Task resolves model via --agent
export ROOT
OUT=$(python3 - <<'PY' "$ROOT"
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "core" / "hooks"))
from before_task_dispatch import evaluate_pre_tool_use

root = Path(sys.argv[1])
payload = {
    "tool_name": "Task",
    "tool_input": {"subagent_type": "sw-coherence-reviewer", "prompt": "review doc"},
    "cwd": str(root),
    "workspace_roots": [str(root)],
}
r = evaluate_pre_tool_use(payload, root)
print(json.dumps({"verdict": r.verdict, "model_id": r.model_id, "hook": r.to_hook_output()}))
PY
)
if echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['verdict']=='pass'
assert d['model_id']=='composer-2.5'
assert d['hook']['updated_input']['model']=='composer-2.5'
"; then
  ok "hook-logic-resolves-reviewer-agent"
else
  bad "hook-logic-resolves-reviewer-agent"
  echo "$OUT"
fi

# Logic: non-reviewer Task skipped
SKIP=$(python3 - <<'PY' "$ROOT"
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "core" / "hooks"))
from before_task_dispatch import evaluate_pre_tool_use
root = Path(sys.argv[1])
r = evaluate_pre_tool_use({"tool_name": "Task", "tool_input": {"subagent_type": "explore"}}, root)
print(r.verdict)
PY
)
if [[ "$SKIP" == "skip" ]]; then
  ok "hook-logic-skips-non-reviewer-task"
else
  bad "hook-logic-skips-non-reviewer-task (got $SKIP)"
fi

# Registration deferred: dist hooks.json must not wire preToolUse task dispatch yet
if [[ -f "$HOOKS_JSON" ]]; then
  if python3 -c "
import json,sys
h=json.load(open(sys.argv[1]))
pretool=h.get('hooks',{}).get('preToolUse',[])
text=json.dumps(pretool)
assert 'before_task_dispatch' not in text and 'before-task-dispatch' not in text
" "$HOOKS_JSON"; then
    ok "hook-not-registered-in-dist-hooks-json"
  else
    bad "hook-not-registered-in-dist-hooks-json"
  fi
else
  ok "hook-not-registered-in-dist-hooks-json (no dist yet)"
fi

if grep -q "model-tier-hook-feasibility" "$ROOT/core/sw-reference/models-tiering.md" 2>/dev/null; then
  ok "models-tiering references feasibility spike"
else
  bad "models-tiering references feasibility spike"
fi

if [[ "$FAIL" -ne 0 ]]; then
  echo "task-dispatch-hook-feasibility: FAIL"
  exit 1
fi
echo "task-dispatch-hook-feasibility: PASS"
