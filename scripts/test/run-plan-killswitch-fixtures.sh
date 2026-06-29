#!/usr/bin/env bash
# orchestration.planPolicy kill-switch + resume semantics fixtures (PRD 022 phase 5 — R29).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VALIDATE="$ROOT/scripts/wave_plan_validate.py"
WF="$ROOT/.cursor/workflow.config.json"
FAIL=0

ok()  { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

FIX=$(mktemp -d)
trap 'rm -rf "$FIX"' EXIT

mkdir -p "$FIX/.cursor" "$FIX/core/sw-reference" "$FIX/scripts"
cp -R "$ROOT/core/sw-reference/." "$FIX/core/sw-reference/"
for f in kernel_classification.py guidelines_validate.py plan_floor_evaluator.py wave_plan_validate.py plan_persist.py wave_deliver.py wave_json_io.py doc_format.py planning_paths.py planning_path_redirect.py; do
  cp "$ROOT/scripts/$f" "$FIX/scripts/"
done

CANONICAL_STEPS='["sw-tmp-init","sw-execute","sw-verify","verification-gate","sw-review","sw-simplify","gap-check","sw-commit","sw-pr","sw-watch-ci","sw-stabilize","sw-ready","sw-tmp-clean"]'

# --- killswitch-canonical-parity ---
cat >"$FIX/.cursor/workflow.config.json" <<'JSON'
{"orchestration":{"planPolicy":"canonical"}}
JSON

if python3 - <<PY
import json, sys
sys.path.insert(0, "$FIX/scripts")
from pathlib import Path
from kernel_classification import canonical_ship_chain
from wave_plan_validate import (
    phase_fallback_canonical_chain,
    read_config_plan_policy,
    plan_stamps,
)

root = Path("$FIX")
chain = canonical_ship_chain(root)
fallback = phase_fallback_canonical_chain(root, "ship", "1")
assert read_config_plan_policy(root) == "canonical", read_config_plan_policy(root)
assert plan_stamps(root)["planPolicy"] == "canonical"
assert fallback["planPolicy"] == "canonical"
assert fallback["steps"] == chain, (fallback["steps"], chain)
PY
then
  ok "killswitch-canonical-parity"
else
  bad "killswitch-canonical-parity"
fi

if OUT=$(python3 "$VALIDATE" "$FIX" validate --tier phase --phase-type ship \
  --proposal "{\"steps\":$CANONICAL_STEPS}" 2>/dev/null) \
  && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['verdict']=='pass'
plan=d.get('plan') or {}
assert plan.get('planPolicy')=='canonical'
assert plan.get('kernelVersion')
assert plan.get('guidelineVersion')
"; then
  ok "killswitch-canonical-parity validate-stamp"
else
  bad "killswitch-canonical-parity validate-stamp"
fi

# --- killswitch-flip-midrun-recorded-mode ---
cat >"$FIX/.cursor/workflow.config.json" <<'JSON'
{"orchestration":{"planPolicy":"proposed"}}
JSON

WAVE_PLAN_FILE="$FIX/wave-plan.json"
if python3 - <<PY
import json, sys
sys.path.insert(0, "$FIX/scripts")
from pathlib import Path
from wave_plan_validate import validate_wave_plan, read_config_plan_policy

root = Path("$FIX")
assert read_config_plan_policy(root) == "proposed"
frozen = {"waves": [["1"], ["2"]], "edges": [{"from": "1", "to": "2"}]}
result = validate_wave_plan(root, {"waves": [["1"], ["2"]]}, frozen_plan=frozen)
assert result["verdict"] == "pass", result
plan = result["plan"]
assert plan["planPolicy"] == "proposed", plan
Path("$WAVE_PLAN_FILE").write_text(json.dumps(plan) + "\n")
PY
then
  ok "killswitch-flip-midrun-recorded-mode wave-stamped-proposed"
else
  bad "killswitch-flip-midrun-recorded-mode wave-stamped-proposed"
fi

cat >"$FIX/.cursor/workflow.config.json" <<'JSON'
{"orchestration":{"planPolicy":"canonical"}}
JSON

if [[ -f "$WAVE_PLAN_FILE" ]] && python3 - <<PY
import json, sys
sys.path.insert(0, "$FIX/scripts")
from pathlib import Path
from wave_plan_validate import (
    resolve_plan_policy_for_proposal,
    read_config_plan_policy,
    phase_fallback_canonical_chain,
)

root = Path("$FIX")
wave_plan = json.loads(Path("$WAVE_PLAN_FILE").read_text())
assert read_config_plan_policy(root) == "canonical"
assert resolve_plan_policy_for_proposal(root, recorded_parent=wave_plan) == "proposed"
phase_plan = phase_fallback_canonical_chain(root, "ship", "1", recorded_parent=wave_plan)
assert phase_plan["planPolicy"] == "proposed", phase_plan
PY
then
  ok "killswitch-flip-midrun-recorded-mode"
else
  bad "killswitch-flip-midrun-recorded-mode"
fi

if grep -q 'run-plan-killswitch-fixtures.sh' "$WF" 2>/dev/null; then
  ok "plan-killswitch-verify-registration"
else
  bad "plan-killswitch-verify-registration"
fi

if [[ "$FAIL" -eq 0 ]]; then
  echo "plan-killswitch fixtures: all passed"
  exit 0
fi
echo "plan-killswitch fixtures: $FAIL failure(s)"
exit 1
