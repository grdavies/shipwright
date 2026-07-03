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
# Two-tier plan persist + deterministic step driver fixtures (PRD 022 phase 4 — R7, R8, R26, R34).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STEPS="$ROOT/scripts/ship-phase-steps.sh"
PERSIST="$ROOT/scripts/plan_persist.py"
LOOP="$ROOT/scripts/wave_deliver_loop.py"
WF="$ROOT/.cursor/workflow.config.json"
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

# --- single-writer-phase-refused ---
mkdir -p .cursor
STATE_PATH="$FIX/.cursor/sw-deliver-state.resume-tier.json"
echo '{"target":{"branch":"feat/resume-tier"},"verdict":"running"}' >"$STATE_PATH"
if SW_CALLER_ROLE=phase python3 "$PERSIST" "$FIX" guarded-state-save --state-path "$STATE_PATH" >/dev/null 2>&1; then
  bad "single-writer-phase-refused"
else
  EC=$?
  if [[ "$EC" -eq 20 ]]; then
    ok "single-writer-phase-refused"
  else
    bad "single-writer-phase-refused (exit $EC)"
  fi
fi

if SW_CALLER_ROLE=conductor OUT=$(python3 "$PERSIST" "$FIX" guarded-state-save --state-path "$STATE_PATH" 2>/dev/null) && \
   echo "$OUT" | python3 -c "import json,sys; assert json.load(sys.stdin)['verdict']=='pass'"; then
  ok "single-writer-conductor-succeeds"
else
  bad "single-writer-conductor-succeeds"
fi

# --- exec-fidelity-out-of-order-halt ---
bash "$STEPS" init --phase alpha --out "$SW_RUN_DIR/ship-steps.json" >/dev/null
bash "$STEPS" advance --step sw-tmp-init --out "$SW_RUN_DIR/ship-steps.json" >/dev/null
if bash "$STEPS" advance --step sw-verify --out "$SW_RUN_DIR/ship-steps.json" >/dev/null 2>&1; then
  bad "exec-fidelity-out-of-order-halt failing-before"
else
  ok "exec-fidelity-out-of-order-halt failing-before"
fi
if bash "$STEPS" advance --step sw-execute --out "$SW_RUN_DIR/ship-steps.json" 2>/dev/null | python3 -c "import json,sys; assert json.load(sys.stdin)['verdict']=='pass'"; then
  ok "exec-fidelity-out-of-order-halt passing-after"
else
  bad "exec-fidelity-out-of-order-halt passing-after"
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
python3 - <<PY2
import json, sys
sys.path.insert(0, "scripts")
from wave_plan_validate import phase_fallback_canonical_chain
from pathlib import Path
plan = phase_fallback_canonical_chain(Path("."), "ship", "1")
Path("$PHASE_PLAN").write_text(json.dumps(plan, indent=2) + "\n")
PY2

# --- resume-between-tiers-rerun-phase-only ---
cat > .cursor/sw-deliver-plan.json <<'JSON'
{"mode":"phase","waves":[["1"]],"items":[{"id":"1","slug":"alpha"}],"edges":[],"target":{"branch":"feat/resume-tier"}}
JSON
python3 - <<PY2
import json, os
from pathlib import Path
state = {
  "target": {"branch": "feat/resume-tier"},
  "verdict": "running",
  "orchestratorWorktree": {"path": "/tmp/orch"},
  "phases": {"1": {"status": "pending", "slug": "alpha"}},
  "twoTierLifecycle": {
    "wave": "wave-validated",
    "phases": {"1": "phase-plan-pending"}
  },
  "currentWave": 1,
  "nextAction": "dispatch-ship",
  "phaseWorktrees": {"1": {"path": os.environ["SW_RUN_DIR"]}},
  "waveBatchingPlan": {
    "version": 1,
    "tier": "wave",
    "waves": [["1"]],
    "planPolicy": "canonical",
    "kernelVersion": "1.0.0",
    "guidelineVersion": "1.0.0"
  },
  "baseCapture": {"name": "main", "sha": "abc", "skipped": True}
}
Path(".cursor/sw-deliver-state.resume-tier.json").write_text(json.dumps(state, indent=2) + "\n")
PY2

if OUT=$(python3 "$LOOP" "$FIX" compute-next 2>/dev/null) && \
   echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['next']['action']=='phase-plan-entry', d
"; then
  ok "resume-between-tiers-rerun-phase-only"
else
  bad "resume-between-tiers-rerun-phase-only"
fi

if python3 -c "import json; r=json.load(open('$ROOT/core/sw-reference/suite-registry.json')); assert any(s['id']=='plan-persist-fixtures' for s in r.get('suites',[]))" 2>/dev/null; then
  ok "plan-persist-verify-registration"
else
  bad "plan-persist-verify-registration"
fi

if [[ "$FAIL" -eq 0 ]]; then
  echo "plan-persist fixtures: all passed"
  exit 0
fi
echo "plan-persist fixtures: $FAIL failure(s)"
exit 1

"""

if __name__ == "__main__":
    raise SystemExit(main())
