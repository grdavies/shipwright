#!/usr/bin/env python3
"""Ported fixture helper (R27)."""
from __future__ import annotations
import os, re, subprocess, sys
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR.parent))
from _sw.vendor_paths import repo_root

from unit_tests._harness_runtime import patch_source as _patch_source

def main() -> int:
    root = repo_root(__file__)
    env = os.environ.copy(); env['ROOT']=str(root)
    env['PYTHONPATH']=str(root/'scripts')+os.pathsep+env.get('PYTHONPATH','')
    return subprocess.run(['bash','-c',_patch_source(_SOURCE,root)],cwd=str(root),env=env,shell=False).returncode
_SOURCE = r"""
#!/usr/bin/env bash
# Hook registration + logic tests for before_task_dispatch (PRD 012 phase 4 / Option C).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
FEAS="$ROOT/core/sw-reference/model-tier-hook-feasibility.md"
CURSOR_HOOKS_JSON="$ROOT/dist/cursor/hooks/hooks.json"
CLAUDE_HOOKS_JSON="$ROOT/dist/claude-code/hooks/hooks.json"
PY="$ROOT/core/hooks/before_task_dispatch.py"

FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

if [[ ! -f "$FEAS" ]]; then
  bad "model-tier-hook-feasibility.md present"
else
  ok "model-tier-hook-feasibility.md present"
  if grep -q "forward-compatible" "$FEAS" && grep -q "Option C" "$FEAS"; then
    ok "feasibility-doc-registered-verdict"
  else
    bad "feasibility-doc-registered-verdict"
  fi
fi

if [[ ! -f "$PY" ]]; then
  bad "before_task_dispatch.py present"
else
  ok "before_task_dispatch.py present"
fi

# Logic: reviewer Task resolves model via fresh dispatch preflight + hook
export ROOT
if ! bash "$ROOT/scripts/wave.sh" dispatch preflight \
  --dispatch-id fixture-hook-test \
  --agent sw-coherence-reviewer \
  --command sw-doc-review \
  --skill doc-review >/dev/null 2>&1; then
  bad "hook-logic-preflight-seed"
  echo "task-dispatch-hook-feasibility: FAIL"
  exit 1
fi
OUT=$(python3 - <<'PY' "$ROOT"
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "core" / "hooks"))
from before_task_dispatch import evaluate_pre_tool_use

root = Path(sys.argv[1])
payload = {
    "tool_name": "Task",
    "tool_input": {"subagent_type": "sw-coherence-reviewer", "prompt": "**Resolved intensity:** `normal` (dispatch-preflight)\nreview doc"},
    "cwd": str(root),
    "workspace_roots": [str(root)],
}
r = evaluate_pre_tool_use(payload, root)
print(json.dumps({"verdict": r.verdict, "model_id": r.model_id, "hook": r.to_hook_output()}))
PY
)
EXPECTED_MODEL=$(bash "$ROOT/scripts/resolve-model-tier.sh" --agent sw-coherence-reviewer --config "$ROOT/.cursor/workflow.config.json" 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin)['modelId'])")
if echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
want=sys.argv[1]
assert d['verdict']=='pass'
assert d['model_id']==want
assert d['hook']['updated_input']['model']==want
" "$EXPECTED_MODEL"; then
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

# Registration: dist/cursor hooks.json must wire preToolUse to before-task-dispatch
if [[ -f "$CURSOR_HOOKS_JSON" ]]; then
  if python3 -c "
import json,sys
h=json.load(open(sys.argv[1]))
pretool=h.get('hooks',{}).get('preToolUse',[])
text=json.dumps(pretool)
assert 'before-task-dispatch' in text
" "$CURSOR_HOOKS_JSON"; then
    ok "hook-registered-in-cursor-hooks-json"
  else
    bad "hook-registered-in-cursor-hooks-json"
  fi
else
  bad "hook-registered-in-cursor-hooks-json (no dist yet)"
fi

# Registration: dist/claude-code hooks.json must wire PreToolUse
if [[ -f "$CLAUDE_HOOKS_JSON" ]]; then
  if python3 -c "
import json,sys
h=json.load(open(sys.argv[1]))
pretool=h.get('hooks',{}).get('PreToolUse',[])
assert len(pretool) > 0
" "$CLAUDE_HOOKS_JSON"; then
    ok "hook-registered-in-claude-hooks-json"
  else
    bad "hook-registered-in-claude-hooks-json"
  fi
else
  bad "hook-registered-in-claude-hooks-json (no dist yet)"
fi

if grep -q "model-tier-hook-feasibility" "$ROOT/core/sw-reference/models-tiering.md" 2>/dev/null; then
  ok "models-tiering references feasibility doc"
else
  bad "models-tiering references feasibility doc"
fi

if [[ "$FAIL" -ne 0 ]]; then
  echo "task-dispatch-hook-feasibility: FAIL"
  exit 1
fi
echo "task-dispatch-hook-feasibility: PASS"

"""
if __name__=="__main__": raise SystemExit(main())
