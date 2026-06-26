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

if [[ "$FAIL" -ne 0 ]]; then
  echo "run-dispatch-foundation-fixtures: FAIL"
  exit 1
fi
echo "run-dispatch-foundation-fixtures: PASS"
