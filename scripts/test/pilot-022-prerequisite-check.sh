#!/usr/bin/env bash
# PRD-022 persist prerequisite subset for PRD-023 TR0 dependency gate.
# Pins: exec-fidelity-out-of-order-halt, resume-two-tier-deterministic, resume-corrupt-plan-fail-closed.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STEPS="$ROOT/scripts/ship-phase-steps.sh"
PERSIST="$ROOT/scripts/plan_persist.py"
FAIL=0

ok()  { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

FIX=$(mktemp -d)
trap 'rm -rf "$FIX"' EXIT

cd "$FIX"
git init -q
git config user.email test@test.com
git config user.name Test
git commit --allow-empty -q -m init
git branch -M main
git checkout -q -b feat/resume-tier

mkdir -p core/sw-reference scripts .cursor/sw-deliver-runs/alpha
cp -R "$ROOT/core/sw-reference/." core/sw-reference/
for f in kernel_classification.py guidelines_validate.py plan_floor_evaluator.py wave_json_io.py \
  wave_plan_validate.py orchestrator_step_plan.py plan_persist.py ship_phase_steps.py wave_state.py wave_deliver.py \
  wave_deliver_loop.py wave_merge.py wave_failure.py; do
  cp "$ROOT/scripts/$f" scripts/
done

export SW_PHASE_SLUG=alpha
export SW_RUN_DIR="$FIX/.cursor/sw-deliver-runs/alpha"

PHASE_PLAN="$SW_RUN_DIR/phase-step-plan.json"
python3 - <<PY2
import json, sys
sys.path.insert(0, "scripts")
from wave_plan_validate import phase_fallback_canonical_chain
from pathlib import Path
plan = phase_fallback_canonical_chain(Path("."), "ship", "1")
Path("$PHASE_PLAN").write_text(json.dumps(plan, indent=2) + "\n")
PY2

# --- exec-fidelity-out-of-order-halt ---
bash "$STEPS" init --phase alpha --out "$SW_RUN_DIR/ship-steps.json" >/dev/null
bash "$STEPS" advance --step sw-tmp-init --out "$SW_RUN_DIR/ship-steps.json" >/dev/null
if bash "$STEPS" advance --step sw-verify --out "$SW_RUN_DIR/ship-steps.json" >/dev/null 2>&1; then
  bad "exec-fidelity-out-of-order-halt"
else
  ok "exec-fidelity-out-of-order-halt"
fi

# --- resume-two-tier-deterministic ---
bash "$STEPS" init --phase alpha --out "$SW_RUN_DIR/ship-steps.json" >/dev/null
bash "$STEPS" advance --step sw-tmp-init --out "$SW_RUN_DIR/ship-steps.json" >/dev/null
if OUT=$(bash "$STEPS" resolve-resume --out "$SW_RUN_DIR/ship-steps.json" 2>/dev/null) && \
   echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['chainSource']=='persisted-plan', d
assert d['nextStep']=='sw-execute', d
"; then
  ok "resume-two-tier-deterministic"
else
  bad "resume-two-tier-deterministic"
fi

# --- resume-corrupt-plan-fail-closed ---
echo '{not-json' >"$PHASE_PLAN"
if bash "$STEPS" validate-plan --out "$SW_RUN_DIR/ship-steps.json" >/dev/null 2>&1; then
  bad "resume-corrupt-plan-fail-closed"
else
  ok "resume-corrupt-plan-fail-closed"
fi

if [[ "$FAIL" -eq 0 ]]; then
  echo "pilot-022-prerequisite: all passed"
  exit 0
fi
echo "pilot-022-prerequisite: $FAIL failure(s)"
exit 1
