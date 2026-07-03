#!/usr/bin/env python3
"""Ported fixture suite (R27) — embedded harness executed without on-disk shell files."""
from __future__ import annotations

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

from _fixture_lib import repo_root
from _harness_patch import harness_subprocess_env as _harness_env
from _harness_patch import patch_source as _patch_source


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
# Phase 1 binding/enforcement fixture smoke tests.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

DISPATCH="$ROOT/scripts/dispatch-check.sh"
CONFIG="$ROOT/.cursor/workflow.config.json"
STATE="$ROOT/scripts/shipwright-state.sh"

PREFLIGHT_DIR="$ROOT/.cursor/hooks/state/task-dispatch-preflight"
WAVE="$ROOT/scripts/wave.sh"
RESOLVE="$ROOT/scripts/resolve-model-tier.sh"

clean_preflight_state() {
  rm -rf "$PREFLIGHT_DIR"
  rm -f "$ROOT/.cursor/hooks/state/task-dispatch-preflight.json"
}

# delegation-mode knob seeded in schemas
if python3 - <<'PY' "$ROOT/.sw/config.schema.json" "$ROOT/core/sw-reference/config.schema.json"
import json, sys
for path in sys.argv[1:]:
    schema = json.load(open(path))
    mode = schema["properties"]["delegation"]["properties"]["mode"]
    assert mode["default"] == "bind-only"
    assert set(mode["enum"]) == {"bind-only", "heuristic", "default"}
PY
then
  ok "delegation-mode-schema"
else
  bad "delegation-mode-schema"
fi

# binding:no-intensity
BROKEN="$ROOT/.cursor/dispatch-foundation-broken.json"
python3 - <<'PY' "$CONFIG" "$BROKEN"
import json, sys
cfg = json.load(open(sys.argv[1]))
cfg = dict(cfg)
comm = dict(cfg.get("communication", {}))
routing = dict(comm.get("routing", {}))
commands = dict(routing.get("commands", {}))
commands["sw-doc-review"] = "wenyan-full"
routing["commands"] = commands
comm["routing"] = routing
cfg["communication"] = comm
json.dump(cfg, open(sys.argv[2], "w"))
PY
set +e
OUT=$(bash "$DISPATCH" --agent sw-coherence-reviewer --command sw-doc-review --parent-model composer-2.5 --config "$BROKEN" 2>/dev/null)
EC=$?
set -e
rm -f "$BROKEN"
if [[ "$EC" -eq 20 ]] && echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('cause')=='binding:no-intensity'"; then
  ok "dispatch-check-no-intensity"
else
  bad "dispatch-check-no-intensity"
fi

# preflight nonce gate
clean_preflight_state
if bash "$ROOT/scripts/wave.sh" dispatch preflight --dispatch-id fixture-preflight --agent sw-coherence-reviewer --command sw-doc-review --skill doc-review >/dev/null 2>&1; then
  HOOK_OUT=$(python3 - <<'PY' "$ROOT"
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "core" / "hooks"))
from before_task_dispatch import evaluate_pre_tool_use
payload = {"tool_name": "Task", "tool_input": {"subagent_type": "sw-coherence-reviewer"}}
result = evaluate_pre_tool_use(payload, Path(sys.argv[1]))
print(json.dumps({"verdict": result.verdict, "cause": result.cause, "model": result.model_id}))
PY
)
  if echo "$HOOK_OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='pass' and d['model']"; then
    ok "dispatch-preflight-nonce-gate"
  else
    bad "dispatch-preflight-nonce-gate"
  fi
else
  bad "dispatch-preflight-nonce-gate"
fi

# override requires durable audit record
OVERRIDE_ID="fixture-override-$$-$(date +%s)"
set +e
OUT=$(bash "$DISPATCH" --agent sw-coherence-reviewer --command sw-doc-review --parent-model composer-2.5-fast --override --dispatch-id "$OVERRIDE_ID" --config "$CONFIG" 2>/dev/null)
EC=$?
set -e
if [[ "$EC" -eq 20 ]] && echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('cause')=='binding:no-override-audit'"; then
  ok "dispatch-check-override-audit-required"
else
  bad "dispatch-check-override-audit-required"
fi

NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
bash "$STATE" dispatch-override-add "$(python3 - <<'PY' "$NOW" "$OVERRIDE_ID"
import json, sys
print(json.dumps({
    "actor": "fixture",
    "timestamp": sys.argv[1],
    "dispatchId": sys.argv[2],
    "skippedFields": ["parentTierFloor"],
}))
PY
)" >/dev/null

set +e
OUT=$(bash "$DISPATCH" --agent sw-coherence-reviewer --command sw-doc-review --parent-model composer-2.5-fast --override --dispatch-id "$OVERRIDE_ID" --config "$CONFIG" 2>/dev/null)
EC=$?
set -e
if [[ "$EC" -eq 0 ]] && echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('verdict')=='pass'"; then
  ok "dispatch-check-override-audit-present"
else
  bad "dispatch-check-override-audit-present"
fi


# --- dispatch-command-tier-inherits-routing (R39) ---
if OUT=$(bash "$DISPATCH" --agent generalPurpose --command sw-prd --parent-model composer-2.5 --config "$CONFIG" 2>/dev/null) &&    echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('tier')=='deep' and d.get('modelId')=='claude-opus-4-8-thinking-high'"; then
  ok "dispatch-command-tier-inherits-routing"
else
  bad "dispatch-command-tier-inherits-routing"
fi

# --- dispatch-command-tier-sw-tasks (R39a) ---
if OUT=$(bash "$DISPATCH" --agent generalPurpose --command sw-tasks --parent-model composer-2.5 --config "$CONFIG" 2>/dev/null) &&    echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('tier')=='deep'"; then
  ok "dispatch-command-tier-sw-tasks"
else
  bad "dispatch-command-tier-sw-tasks"
fi

# --- dispatch-agent-explicit-override-wins (R39b) ---
if OUT=$(bash "$DISPATCH" --agent sw-coherence-reviewer --command sw-prd --parent-model claude-opus-4-8-thinking-high --config "$CONFIG" 2>/dev/null) &&    echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('tier')=='build' and d.get('modelId')=='composer-2.5'"; then
  ok "dispatch-agent-explicit-override-wins"
else
  bad "dispatch-agent-explicit-override-wins"
fi

# --- dispatch-preflight-command-model-parity (R39c/R39d) ---
clean_preflight_state
CMD_MODEL=$(bash "$RESOLVE" --command sw-prd --config "$CONFIG" 2>/dev/null)
if bash "$WAVE" dispatch preflight --dispatch-id fixture-cmd-parity --agent generalPurpose --command sw-prd >/dev/null 2>&1; then
  REC=$(python3 -c "import json; print(json.load(open('$PREFLIGHT_DIR/fixture-cmd-parity.json'))['modelId'])")
  EXP=$(echo "$CMD_MODEL" | python3 -c "import json,sys; print(json.load(sys.stdin)['modelId'])")
  if [[ "$REC" == "$EXP" && -n "$REC" ]]; then
    ok "dispatch-preflight-command-model-parity"
  else
    bad "dispatch-preflight-command-model-parity (rec=$REC exp=$EXP)"
  fi
else
  bad "dispatch-preflight-command-model-parity"
fi
clean_preflight_state

# --- dispatch-preflight-parallel-n-personas (R38) ---
PAR_OK=1
clean_preflight_state
bash "$WAVE" dispatch preflight --dispatch-id fixture-parallel-a --agent sw-coherence-reviewer --command sw-doc-review --skill doc-review >/dev/null 2>&1 || PAR_OK=0
bash "$WAVE" dispatch preflight --dispatch-id fixture-parallel-b --agent sw-feasibility-reviewer --command sw-doc-review --skill doc-review >/dev/null 2>&1 || PAR_OK=0
bash "$WAVE" dispatch preflight --dispatch-id fixture-parallel-c --agent sw-scope-guardian-reviewer --command sw-doc-review --skill doc-review >/dev/null 2>&1 || PAR_OK=0
if [[ "$PAR_OK" -eq 1 ]]; then
  HOOK1=$(python3 - "$ROOT" fixture-parallel-a sw-coherence-reviewer <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / 'core' / 'hooks'))
from before_task_dispatch import evaluate_pre_tool_use
payload = {'tool_name': 'Task', 'tool_input': {'subagent_type': sys.argv[3], 'metadata': {'dispatchId': sys.argv[2]}}}
result = evaluate_pre_tool_use(payload, Path(sys.argv[1]))
print(json.dumps({'verdict': result.verdict, 'cause': result.cause}))
PY
)
  HOOK2=$(python3 - "$ROOT" fixture-parallel-b sw-feasibility-reviewer <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / 'core' / 'hooks'))
from before_task_dispatch import evaluate_pre_tool_use
payload = {'tool_name': 'Task', 'tool_input': {'subagent_type': sys.argv[3], 'metadata': {'dispatchId': sys.argv[2]}}}
result = evaluate_pre_tool_use(payload, Path(sys.argv[1]))
print(json.dumps({'verdict': result.verdict, 'cause': result.cause}))
PY
)
  if echo "$HOOK1" | python3 -c "import json,sys; assert json.load(sys.stdin)['verdict']=='pass'" &&      echo "$HOOK2" | python3 -c "import json,sys; assert json.load(sys.stdin)['verdict']=='pass'"; then
    ok "dispatch-preflight-parallel-n-personas"
  else
    bad "dispatch-preflight-parallel-n-personas"
    echo "HOOK1=$HOOK1 HOOK2=$HOOK2"
  fi
else
  bad "dispatch-preflight-parallel-n-personas (preflight seed)"
fi
clean_preflight_state

# --- dispatch-preflight-ambiguous-agent-fail-closed (R38c) ---
clean_preflight_state
bash "$WAVE" dispatch preflight --dispatch-id fixture-amb-a --agent sw-coherence-reviewer --command sw-doc-review >/dev/null 2>&1
bash "$WAVE" dispatch preflight --dispatch-id fixture-amb-b --agent sw-coherence-reviewer --command sw-doc-review >/dev/null 2>&1
AMB_OUT=$(python3 - "$ROOT" <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / 'core' / 'hooks'))
from before_task_dispatch import evaluate_pre_tool_use
payload = {'tool_name': 'Task', 'tool_input': {'subagent_type': 'sw-coherence-reviewer'}}
result = evaluate_pre_tool_use(payload, Path(sys.argv[1]))
print(json.dumps({'verdict': result.verdict, 'cause': result.cause}))
PY
)
if echo "$AMB_OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='fail' and d['cause']=='preflight-dispatch-ambiguous'"; then
  ok "dispatch-preflight-ambiguous-agent-fail-closed"
else
  bad "dispatch-preflight-ambiguous-agent-fail-closed ($AMB_OUT)"
fi
clean_preflight_state


if [[ "$FAIL" -ne 0 ]]; then
  echo "run-dispatch-foundation-fixtures: FAIL"
  exit 1
fi
echo "run-dispatch-foundation-fixtures: PASS"

"""

if __name__ == "__main__":
    raise SystemExit(main())
