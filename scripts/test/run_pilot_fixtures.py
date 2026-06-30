#!/usr/bin/env python3
"""Ported fixture suite (R27) — embedded harness executed without on-disk shell files."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR.parent))

from _fixture_lib import repo_root
from _harness_patch import patch_source as _patch_source


def main() -> int:
    root = repo_root(__file__)
    env = os.environ.copy()
    env["ROOT"] = str(root)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(root / "scripts" / "test"), str(root / "scripts"), env.get("PYTHONPATH", "")) if p
    )
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
# PRD 023 — dependency gate, proposed-path deliver wiring, E2E + 022 parity (TR0, TR1, TR5a, TR5c),
# intra-phase safety (R15–R17), and benefit metric capture + decision rule (TR4, TR5b, R31).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GATE_PY="$ROOT/scripts/pilot_dependency_gate.py"
PREREQ="$ROOT/scripts/test/pilot-022-prerequisite-check.sh"
PERSIST_FIX="$ROOT/scripts/test/run-plan-persist-fixtures.sh"
PARITY_FIX="$ROOT/scripts/test/run-plan-proposed-parity-fixtures.sh"
INTRA_PY="$ROOT/scripts/intra_phase_dispatch.py"
INTRA_SH="$ROOT/scripts/intra-phase-dispatch.sh"
LOOP_PY="$ROOT/scripts/wave_deliver_loop.py"
STATE_PY="$ROOT/scripts/wave_state.py"
BENEFIT_PY="$ROOT/scripts/wave_plan_benefit.py"
WAVE_SH="$ROOT/scripts/wave.sh"
POSITIVE_PAIRS="$ROOT/scripts/test/fixtures/benefit-metric/positive-pairs.json"
INSUFFICIENT_PAIRS="$ROOT/scripts/test/fixtures/benefit-metric/insufficient-n-pairs.json"
WF="$ROOT/.cursor/workflow.config.json"
FAIL=0

ok()  { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

# --- pilot-dependency-gate: verify.test ordering ---
if grep -q 'run-plan-persist-fixtures.sh' "$WF" 2>/dev/null \
  && grep -q 'run-pilot-fixtures.sh' "$WF" 2>/dev/null; then
  if python3 - <<PY
from pathlib import Path
text = Path("$WF").read_text()
persist = text.index("run-plan-persist-fixtures.sh")
pilot = text.index("run-pilot-fixtures.sh")
assert persist < pilot, "run-plan-persist-fixtures must precede run-pilot-fixtures in verify.test"
PY
  then
    ok "pilot-dependency-gate verify-ordering"
  else
    bad "pilot-dependency-gate verify-ordering"
  fi
else
  bad "pilot-dependency-gate verify-registration"
fi

# --- pilot-dependency-gate: prerequisite fixtures pass ---
if bash "$PREREQ" >/dev/null 2>&1; then
  ok "pilot-dependency-gate prerequisite-fixtures-pass"
else
  bad "pilot-dependency-gate prerequisite-fixtures-pass"
fi

# --- pilot-dependency-gate: proposed refused when gate unsatisfied (failing-before) ---
GATE_FIX=$(mktemp -d)
(
  cd "$GATE_FIX"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  git commit --allow-empty -q -m init
  git branch -M main
  mkdir -p .cursor scripts core/sw-reference
  cp -R "$ROOT/core/sw-reference/." core/sw-reference/
  for f in kernel_classification.py guidelines_validate.py plan_floor_evaluator.py wave_json_io.py \
    wave_plan_validate.py orchestrator_step_plan.py plan_persist.py pilot_dependency_gate.py wave_state.py wave_deliver.py; do
    cp "$ROOT/scripts/$f" scripts/
  done
  cat >.cursor/workflow.config.json <<'JSON'
{"orchestration":{"planPolicy":"proposed"},"defaultBaseBranch":"main"}
JSON
  cat >.cursor/sw-deliver-plan.json <<'JSON'
{"mode":"phase","target":{"branch":"feat/gate-test"},"items":[{"id":"1","slug":"alpha"}],"waves":[["1"]]}
JSON
  # Broken ship_phase_steps — prerequisite gate fails when script missing/broken
  rm -f scripts/test/pilot-022-prerequisite-check.sh
  set +e
  python3 scripts/wave_state.py "$GATE_FIX" state init --plan .cursor/sw-deliver-plan.json >/dev/null 2>&1
  EC=$?
  set -e
  if [[ "$EC" -eq 20 ]]; then
    exit 0
  fi
  exit 1
) && ok "pilot-dependency-gate proposed-refused-without-prereq" \
  || bad "pilot-dependency-gate proposed-refused-without-prereq"
rm -rf "$GATE_FIX"

# --- pilot-dependency-gate: proposed seeds two-tier lifecycle when gate satisfied ---
SEED_FIX=$(mktemp -d)
(
  cd "$SEED_FIX"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  git commit --allow-empty -q -m init
  git branch -M main
  git checkout -qb feat/gate-seed
  mkdir -p .cursor scripts/test core/sw-reference
  cp -R "$ROOT/core/sw-reference/." core/sw-reference/
  cp "$PREREQ" scripts/test/pilot-022-prerequisite-check.sh
  for f in kernel_classification.py guidelines_validate.py plan_floor_evaluator.py wave_json_io.py \
    wave_plan_validate.py orchestrator_step_plan.py plan_persist.py pilot_dependency_gate.py wave_state.py wave_deliver.py \
    ship_phase_steps.py wave_deliver_loop.py wave_merge.py wave_failure.py plan_persist.py deliver_plan_surfacing.py \
    status_integrity.py; do
    cp "$ROOT/scripts/$f" scripts/ 2>/dev/null || true
  done
  cp "$ROOT/scripts/ship-phase-steps.sh" scripts/
  cat >.cursor/workflow.config.json <<'JSON'
{"orchestration":{"planPolicy":"proposed"},"defaultBaseBranch":"main"}
JSON
  cat >.cursor/sw-deliver-plan.json <<'JSON'
{"mode":"phase","target":{"branch":"feat/gate-seed"},"items":[{"id":"1","slug":"alpha"}],"waves":[["1"]]}
JSON
  if OUT=$(python3 scripts/wave_state.py "$SEED_FIX" state init --plan .cursor/sw-deliver-plan.json 2>/dev/null) \
    && python3 - <<PY
import json, sys
from pathlib import Path
state = json.loads(Path(".cursor/sw-deliver-state.gate-seed.json").read_text())
assert "twoTierLifecycle" in state, state.keys()
assert state["twoTierLifecycle"]["wave"] is None
assert state["twoTierLifecycle"]["phases"] == {}
assert "planRejectionLog" in state
assert isinstance(state["planRejectionLog"], dict)
PY
  then
    exit 0
  fi
  exit 1
) && ok "pilot-dependency-gate proposed-seeds-lifecycle" \
  || bad "pilot-dependency-gate proposed-seeds-lifecycle"
rm -rf "$SEED_FIX"

# --- pilot-e2e-proposed-terminal-gate ---
E2E_FIX=$(mktemp -d)
(
  cd "$E2E_FIX"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  git commit --allow-empty -q -m init
  git branch -M main
  mkdir -p .cursor scripts/test core/sw-reference
  cp -R "$ROOT/core/sw-reference/." core/sw-reference/
  cp "$PREREQ" scripts/test/pilot-022-prerequisite-check.sh
  for f in kernel_classification.py guidelines_validate.py plan_floor_evaluator.py wave_json_io.py \
    wave_plan_validate.py orchestrator_step_plan.py plan_persist.py pilot_dependency_gate.py wave_state.py wave_deliver.py \
    wave_deliver_loop.py wave_merge.py wave_failure.py wave_terminal.py wave_compound.py deliver_plan_surfacing.py \
    host_lib.py host_invoke.py status_integrity.py planning_paths.py; do
    cp "$ROOT/scripts/$f" scripts/
  done
  cp "$ROOT/scripts/ship-phase-steps.sh" scripts/
  cat >.cursor/workflow.config.json <<'JSON'
{"orchestration":{"planPolicy":"proposed"},"defaultBaseBranch":"main","deliver":{"terminal":{"autonomy":"auto"}}}
JSON
  cat >.cursor/sw-base-state.json <<'JSON'
{"trunkBase": {"name": "main", "sha": "deadbeef00000000000000000000000000000000"}}
JSON
  cat >.cursor/sw-deliver-plan.json <<'JSON'
{
  "verdict": "pass",
  "mode": "phase",
  "source_task_list": "docs/prds/023-x/tasks.md",
  "target": {"branch": "feat/pilot-e2e"},
  "items": [
    {"id": "1", "slug": "alpha", "branch": "feat/pilot-e2e-phase-alpha"},
    {"id": "2", "slug": "beta", "branch": "feat/pilot-e2e-phase-beta"}
  ],
  "edges": [{"from": "1", "to": "2"}],
  "waves": [["1"], ["2"]]
}
JSON
  NOW_TS=$(python3 -c "from datetime import datetime,timezone; print(datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))")
  cat >.cursor/sw-deliver-state.pilot-e2e.json <<JSON
{
  "verdict": "running",
  "target": {"branch": "feat/pilot-e2e"},
  "source_task_list": "docs/prds/023-x/tasks.md",
  "currentWave": 1,
  "nextAction": "wave-plan-persist",
  "orchestratorWorktree": {"path": "/tmp/orch"},
  "specSeed": {"skipped": true},
  "baseCapture": {"skipped": true},
  "driverHeartbeatAt": "$NOW_TS",
  "twoTierLifecycle": {"wave": null, "phases": {}},
  "planRejectionLog": {"version": 1, "threshold": 3, "phases": {}, "halt": null},
  "phases": {
    "1": {"id": "1", "slug": "alpha", "status": "pending"},
    "2": {"id": "2", "slug": "beta", "status": "pending"}
  },
  "phaseWorktrees": {
    "1": {"path": "/tmp/alpha", "name": "alpha"},
    "2": {"path": "/tmp/beta", "name": "beta"}
  }
}
JSON
  # wave-plan-persist under proposed
  if ! OUT=$(python3 scripts/wave_deliver_loop.py "$E2E_FIX" compute-next 2>/dev/null) \
    || ! echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['next']['action']=='wave-plan-persist', d
"; then
    exit 1
  fi
  if ! python3 - <<PY
import json, subprocess, sys
from pathlib import Path
sys.path.insert(0, "scripts")
from wave_deliver_loop import execute_mechanical, load_plan, load_state, save_state
from wave_state import load_deliver_state

root = Path("$E2E_FIX")
state = load_deliver_state(root)
plan = json.loads(Path(".cursor/sw-deliver-plan.json").read_text())
step = {"action": "wave-plan-persist"}
result = execute_mechanical(root, state, plan, step)
assert result["executed"] == "wave-plan-persist"
state = load_deliver_state(root)
assert state.get("waveBatchingPlan"), state.keys()
assert state.get("twoTierLifecycle", {}).get("wave") == "wave-validated"
PY
  then
    exit 1
  fi
  # All phases merged → terminal-ship path
  cat >.cursor/sw-deliver-state.pilot-e2e.json <<JSON
{
  "verdict": "running",
  "target": {"branch": "feat/pilot-e2e"},
  "source_task_list": "docs/prds/023-x/tasks.md",
  "currentWave": 2,
  "nextAction": "retrospective",
  "orchestratorWorktree": {"path": "/tmp/orch"},
  "specSeed": {"skipped": true},
  "baseCapture": {"skipped": true},
  "driverHeartbeatAt": "$NOW_TS",
  "waveBatchingPlan": {"version": 1, "tier": "wave", "waves": [["1"], ["2"]], "planPolicy": "proposed"},
  "twoTierLifecycle": {"wave": "wave-validated", "phases": {"1": "phase-plan-validated", "2": "phase-plan-validated"}},
  "compoundShip": {"premergeDone": true},
  "phases": {
    "1": {"id": "1", "slug": "alpha", "status": "green-merged"},
    "2": {"id": "2", "slug": "beta", "status": "green-merged"}
  }
}
JSON
  if OUT=$(python3 scripts/wave_deliver_loop.py "$E2E_FIX" compute-next 2>/dev/null) \
    && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['next']['action']=='terminal-ship', d
"; then
    exit 0
  fi
  exit 1
) && ok "pilot-e2e-proposed-terminal-gate" \
  || bad "pilot-e2e-proposed-terminal-gate"
rm -rf "$E2E_FIX"

# --- pilot-022-parity-suite-under-proposed ---
if bash "$PARITY_FIX" >/dev/null 2>&1; then
  ok "pilot-022-parity-suite-under-proposed"
else
  bad "pilot-022-parity-suite-under-proposed"
fi

# --- benefit-metric-no-sensitive-fields ---
if python3 - <<PY
import sys
sys.path.insert(0, "$ROOT/scripts")
from wave_plan_benefit import build_benefit_metric, sensitive_field_violations, validate_benefit_metric
from pathlib import Path

root = Path("$ROOT")
metric = build_benefit_metric(
    plan_policy="proposed",
    kernel_verdict={"terminalPhaseStatuses": ["green-merged"], "gateOutcome": "green", "mergeReadyCount": 1},
    executed_step_set=["sw-tmp-init", "sw-execute", "sw-commit", "sw-ready"],
    stabilize_reentries=[],
    escaped_defect_signal="none",
    phase_wall_clock_ms=120000,
    root=root,
)
assert not sensitive_field_violations(metric), sensitive_field_violations(metric)
ok, reasons = validate_benefit_metric(metric)
assert ok, reasons
bad_metric = dict(metric)
bad_metric["notes"] = "secret transcript excerpt"
violations = sensitive_field_violations(bad_metric)
assert violations, violations
PY
then
  ok "benefit-metric-no-sensitive-fields"
else
  bad "benefit-metric-no-sensitive-fields"
fi

# --- benefit-refuses-credit-on-later-stabilize ---
if python3 - <<PY
import sys
sys.path.insert(0, "$ROOT/scripts")
from wave_plan_benefit import compute_steps_skipped_without_rework

canonical = ["sw-tmp-init", "sw-execute", "sw-verify", "sw-simplify", "sw-commit", "sw-ready"]
executed = ["sw-tmp-init", "sw-execute", "sw-commit", "sw-ready"]
without = compute_steps_skipped_without_rework(canonical, executed, [])
assert without == 2, without
with_rework = compute_steps_skipped_without_rework(
    canonical,
    executed,
    [{"step": "sw-verify", "attributed": True}],
)
assert with_rework == 1, with_rework
all_zero = compute_steps_skipped_without_rework(
    canonical,
    executed,
    [
        {"step": "sw-verify", "attributed": True},
        {"step": "sw-simplify", "attributed": True},
    ],
)
assert all_zero == 0, all_zero
PY
then
  ok "benefit-refuses-credit-on-later-stabilize"
else
  bad "benefit-refuses-credit-on-later-stabilize"
fi

# --- pilot-atypical-phase-step-omit ---
if python3 - <<PY
import sys
sys.path.insert(0, "$ROOT/scripts")
from wave_plan_benefit import build_benefit_metric
from pathlib import Path

root = Path("$ROOT")
kernel = {"terminalPhaseStatuses": ["green-merged"], "gateOutcome": "green", "mergeReadyCount": 1}
canonical_chain = [
    "sw-tmp-init", "sw-execute", "sw-verify", "verification-gate", "sw-review",
    "sw-simplify", "gap-check", "sw-commit", "sw-pr", "sw-watch-ci", "sw-stabilize", "sw-ready", "sw-tmp-clean",
]
# docs-only atypical phase: gate-accepted proposed plan omits verify/simplify
proposed_executed = [s for s in canonical_chain if s not in ("sw-verify", "sw-simplify")]
metric = build_benefit_metric(
    plan_policy="proposed",
    kernel_verdict=kernel,
    canonical_step_set=canonical_chain,
    executed_step_set=proposed_executed,
    stabilize_reentries=[],
    escaped_defect_signal="none",
    phase_wall_clock_ms=80000,
    decomposed={"stepPlanAdaptivity": {"stepsSkipped": 2, "wallClockMs": 20000}, "waveSchedule": {"wallClockMs": 0}, "intraPhase": {"wallClockMs": 0}},
    root=root,
)
assert metric["stepsSkippedWithoutRework"] == 2, metric
assert metric["decomposed"]["stepPlanAdaptivity"]["stepsSkipped"] == 2
PY
then
  ok "pilot-atypical-phase-step-omit"
else
  bad "pilot-atypical-phase-step-omit"
fi

# --- benefit-decision-rule-fail-closed (insufficient N) ---
if OUT=$(bash "$WAVE_SH" plan benefit-report --pairs "$INSUFFICIENT_PAIRS" --min-n 3 2>/dev/null) \
  && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['decision']['recommendation']=='canonical', d
assert d['decision']['failClosed'] is True, d
"; then
  ok "benefit-decision-rule-fail-closed insufficient-n"
else
  bad "benefit-decision-rule-fail-closed insufficient-n"
fi

# --- benefit-decision-rule-fail-closed (non-positive steps-skipped) ---
NONPOS_FIX=$(mktemp -d)
cat >"$NONPOS_FIX/pairs.json" <<'JSON'
{
  "pairs": [
    {
      "canonical": {
        "planPolicy": "canonical",
        "kernelVerdict": {"terminalPhaseStatuses": ["green-merged"], "gateOutcome": "green", "mergeReadyCount": 1},
        "canonicalStepSet": ["sw-tmp-init", "sw-execute", "sw-verify", "sw-commit", "sw-ready"],
        "executedStepSet": ["sw-tmp-init", "sw-execute", "sw-verify", "sw-commit", "sw-ready"],
        "stepsSkippedWithoutRework": 0,
        "stabilizeReentries": [],
        "escapedDefectSignal": "none",
        "phaseWallClockMs": 100000,
        "decomposed": {"stepPlanAdaptivity": {"stepsSkipped": 0, "wallClockMs": 0}, "waveSchedule": {"wallClockMs": 0}, "intraPhase": {"wallClockMs": 0}}
      },
      "proposed": {
        "planPolicy": "proposed",
        "kernelVerdict": {"terminalPhaseStatuses": ["green-merged"], "gateOutcome": "green", "mergeReadyCount": 1},
        "canonicalStepSet": ["sw-tmp-init", "sw-execute", "sw-verify", "sw-commit", "sw-ready"],
        "executedStepSet": ["sw-tmp-init", "sw-execute", "sw-verify", "sw-commit", "sw-ready"],
        "stepsSkippedWithoutRework": 0,
        "stabilizeReentries": [],
        "escapedDefectSignal": "none",
        "phaseWallClockMs": 90000,
        "decomposed": {"stepPlanAdaptivity": {"stepsSkipped": 0, "wallClockMs": 0}, "waveSchedule": {"wallClockMs": 0}, "intraPhase": {"wallClockMs": 0}}
      }
    },
    {
      "canonical": {
        "planPolicy": "canonical",
        "kernelVerdict": {"terminalPhaseStatuses": ["green-merged"], "gateOutcome": "green", "mergeReadyCount": 1},
        "canonicalStepSet": ["sw-tmp-init", "sw-execute", "sw-verify", "sw-commit", "sw-ready"],
        "executedStepSet": ["sw-tmp-init", "sw-execute", "sw-verify", "sw-commit", "sw-ready"],
        "stepsSkippedWithoutRework": 0,
        "stabilizeReentries": [],
        "escapedDefectSignal": "none",
        "phaseWallClockMs": 100000,
        "decomposed": {"stepPlanAdaptivity": {"stepsSkipped": 0, "wallClockMs": 0}, "waveSchedule": {"wallClockMs": 0}, "intraPhase": {"wallClockMs": 0}}
      },
      "proposed": {
        "planPolicy": "proposed",
        "kernelVerdict": {"terminalPhaseStatuses": ["green-merged"], "gateOutcome": "green", "mergeReadyCount": 1},
        "canonicalStepSet": ["sw-tmp-init", "sw-execute", "sw-verify", "sw-commit", "sw-ready"],
        "executedStepSet": ["sw-tmp-init", "sw-execute", "sw-verify", "sw-commit", "sw-ready"],
        "stepsSkippedWithoutRework": 0,
        "stabilizeReentries": [],
        "escapedDefectSignal": "none",
        "phaseWallClockMs": 90000,
        "decomposed": {"stepPlanAdaptivity": {"stepsSkipped": 0, "wallClockMs": 0}, "waveSchedule": {"wallClockMs": 0}, "intraPhase": {"wallClockMs": 0}}
      }
    },
    {
      "canonical": {
        "planPolicy": "canonical",
        "kernelVerdict": {"terminalPhaseStatuses": ["green-merged"], "gateOutcome": "green", "mergeReadyCount": 1},
        "canonicalStepSet": ["sw-tmp-init", "sw-execute", "sw-verify", "sw-commit", "sw-ready"],
        "executedStepSet": ["sw-tmp-init", "sw-execute", "sw-verify", "sw-commit", "sw-ready"],
        "stepsSkippedWithoutRework": 0,
        "stabilizeReentries": [],
        "escapedDefectSignal": "none",
        "phaseWallClockMs": 100000,
        "decomposed": {"stepPlanAdaptivity": {"stepsSkipped": 0, "wallClockMs": 0}, "waveSchedule": {"wallClockMs": 0}, "intraPhase": {"wallClockMs": 0}}
      },
      "proposed": {
        "planPolicy": "proposed",
        "kernelVerdict": {"terminalPhaseStatuses": ["green-merged"], "gateOutcome": "green", "mergeReadyCount": 1},
        "canonicalStepSet": ["sw-tmp-init", "sw-execute", "sw-verify", "sw-commit", "sw-ready"],
        "executedStepSet": ["sw-tmp-init", "sw-execute", "sw-verify", "sw-commit", "sw-ready"],
        "stepsSkippedWithoutRework": 0,
        "stabilizeReentries": [],
        "escapedDefectSignal": "none",
        "phaseWallClockMs": 90000,
        "decomposed": {"stepPlanAdaptivity": {"stepsSkipped": 0, "wallClockMs": 0}, "waveSchedule": {"wallClockMs": 0}, "intraPhase": {"wallClockMs": 0}}
      }
    }
  ]
}
JSON
if OUT=$(bash "$WAVE_SH" plan benefit-report --pairs "$NONPOS_FIX/pairs.json" --min-n 3 2>/dev/null) \
  && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['decision']['recommendation']=='canonical', d
"; then
  ok "benefit-decision-rule-fail-closed non-positive"
else
  bad "benefit-decision-rule-fail-closed non-positive"
fi
rm -rf "$NONPOS_FIX"

# --- wave.sh plan benefit-report positive cohort ---
if OUT=$(bash "$WAVE_SH" plan benefit-report --pairs "$POSITIVE_PAIRS" --min-n 3 2>/dev/null) \
  && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['decision']['recommendation']=='proposed-eligible', d
assert d['decision']['failClosed'] is False, d
assert d['summary']['stepsSkippedWithoutRework']['delta'] == 6, d
"; then
  ok "benefit-decision-rule-positive-cohort"
else
  bad "benefit-decision-rule-positive-cohort"
fi

# --- intra-phase-disjoint-partition-required (R15) ---
if OUT=$(python3 "$INTRA_PY" "$ROOT" evaluate --context-json '{}' \
  --proposal-json '{"partitions":[{"workerId":"a","files":["src/a.py"]},{"workerId":"b","files":["src/a.py"]}],"proposedWorkers":2}' 2>/dev/null) \
  && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('verdict') in ('serialize','reject'), d
assert d.get('partition',{}).get('verdict') in ('serialize','reject'), d
"; then
  ok "intra-phase-disjoint-partition-required"
else
  bad "intra-phase-disjoint-partition-required"
fi

# --- intra-phase-global-cap (R15) ---
set +e
OUT=$(python3 "$INTRA_PY" "$ROOT" evaluate \
  --context-json '{"file_paths":["a.py","b.py","c.py"],"derived_tags":["review-panel"]}' \
  --wave-slots 4 --active-intra-phase 0 2>/dev/null)
EC=$?
set -e
if [[ "$EC" -eq 20 ]] && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('verdict')=='reject', d
assert d.get('cause')=='cap:global', d
cap=d.get('cap',{})
assert cap.get('globalCap') == 4, cap
assert cap.get('waveSlots') == 4, cap
"; then
  ok "intra-phase-global-cap"
else
  bad "intra-phase-global-cap"
fi

# --- intra-phase-no-durable-write-race (R15) ---
if OUT=$(python3 "$INTRA_PY" "$ROOT" evaluate \
  --context-json '{"file_paths":["src/a.py","src/b.py"],"derived_tags":["review-panel"]}' \
  --wave-slots 0 --active-intra-phase 0 2>/dev/null) \
  && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
files=set(d.get('decision',{}).get('readOnlyDurableFiles') or [])
assert files == {'ship-steps.json','status.json'}, files
"; then
  ok "intra-phase-no-durable-write-race"
else
  bad "intra-phase-no-durable-write-race"
fi

# --- intra-phase-background-degrade-before-dispatch (R16) ---
BG_FIX=$(mktemp -d)
(
  RUN_DIR="$BG_FIX/.cursor/sw-deliver-runs/bg-phase"
  mkdir -p "$RUN_DIR"
  python3 "$INTRA_PY" "$BG_FIX" stamp-context --run-dir "$RUN_DIR" --conductor-mode background_phase >/dev/null
  if OUT=$(python3 "$INTRA_PY" "$BG_FIX" check-nesting --run-dir "$RUN_DIR" \
    --context-json '{"conductor_mode":"background_phase"}' 2>/dev/null) \
    && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('taskSpawnAllowed') is False, d
assert d.get('nestedTaskSpawns') == 0, d
evald=d.get('evaluation',{})
assert evald.get('verdict')=='inline', evald
"; then
    exit 0
  fi
  exit 1
) && ok "intra-phase-background-degrade-before-dispatch" \
  || bad "intra-phase-background-degrade-before-dispatch"
rm -rf "$BG_FIX"

# --- intra-phase-decision-logged (R17) ---
LOG_FIX=$(mktemp -d)
(
  RUN_DIR="$LOG_FIX/.cursor/sw-deliver-runs/log-phase"
  mkdir -p "$RUN_DIR"
  if OUT=$(python3 "$INTRA_PY" "$LOG_FIX" evaluate \
    --context-json '{"file_paths":["src/x.py"],"derived_tags":["review-panel"]}' \
    --wave-slots 0 --active-intra-phase 0 --run-dir "$RUN_DIR" --record 2>/dev/null) \
    && test -f "$RUN_DIR/dispatch-decisions.json" \
    && python3 - <<PY
import json
from pathlib import Path
doc = json.loads(Path("$RUN_DIR/dispatch-decisions.json").read_text())
assert doc.get("version") == 1
assert isinstance(doc.get("decisions"), list) and doc["decisions"]
row = doc["decisions"][-1]
for key in ("timestamp","signals","declaredPartition","chosenParallelism","degradeReason"):
    assert key in row, key
PY
  then
    exit 0
  fi
  exit 1
) && ok "intra-phase-decision-logged" \
  || bad "intra-phase-decision-logged"
rm -rf "$LOG_FIX"


# --- deliver-plan-surfacing (R21) ---
SURF_FIX=$(mktemp -d)
(
  RUN_DIR="$SURF_FIX/.cursor/sw-deliver-runs/alpha-phase"
  mkdir -p "$RUN_DIR"
  cat >"$RUN_DIR/phase-step-plan.json" <<'JSON'
{"version":1,"tier":"phase","phaseType":"ship","phaseId":"1","steps":["sw-tmp-init","sw-execute","sw-commit","sw-ready"],"planPolicy":"proposed","kernelVersion":"1.0.0","guidelineVersion":"1.0.0"}
JSON
  cat >"$SURF_FIX/.cursor/sw-deliver-runs/run.log" <<'JSON'
{"event":"capability-selection","resolvedCapabilities":["persona.sw-security-reviewer"],"inputsHash":"abc123","precedenceTrace":["phase_default"],"phaseType":"sw-doc-review","at":"2026-06-27T00:00:00Z"}
JSON
  cat >"$SURF_FIX/.cursor/sw-deliver-state.surf-test.json" <<'JSON'
{
  "target": {"branch": "feat/surf-test"},
  "waveBatchingPlan": {"version":1,"tier":"wave","waves":[["1"]],"planPolicy":"proposed","kernelVersion":"1.0.0","guidelineVersion":"1.0.0"},
  "planRejectionLog": {
    "version": 1,
    "threshold": 3,
    "phases": {
      "1": {
        "consecutiveRejections": 1,
        "entries": [{"at":"2026-06-27T00:00:00Z","verdict":"reject","tier":"phase","reasons":["out-of-order:sw-verify"]}]
      }
    },
    "halt": null
  },
  "phases": {"1": {"id":"1","slug":"alpha-phase","status":"green-merged"}}
}
JSON
  if python3 - <<PY2
import json, sys
from pathlib import Path
sys.path.insert(0, "$ROOT/scripts")
from deliver_plan_surfacing import build_plan_surfacing_snapshot, attach_plan_surfacing_to_report, REPORT_KIND_TERMINAL
from wave_state import load_deliver_state

root = Path("$SURF_FIX")
state = json.loads(Path("$SURF_FIX/.cursor/sw-deliver-state.surf-test.json").read_text())
snapshot = build_plan_surfacing_snapshot(root, state)
assert snapshot.get("waveBatchingPlan"), snapshot
assert snapshot.get("phaseStepPlans", {}).get("alpha-phase"), snapshot
rejections = snapshot.get("planRejections", {}).get("rejections") or []
assert rejections and rejections[0].get("reasons"), snapshot
caps = snapshot.get("resolvedCapabilities") or []
assert caps and caps[0].get("resolvedCapabilities"), snapshot
report = {}
attach_plan_surfacing_to_report(root, state, report, report_kind=REPORT_KIND_TERMINAL)
assert report.get("planSurfacing"), report
log = Path("$SURF_FIX/.cursor/sw-deliver-runs/run.log").read_text(encoding="utf-8")
assert any(json.loads(line).get("event") == "deliver-plan-surfacing" for line in log.splitlines() if line.strip()), log
PY2
  then
    exit 0
  fi
  exit 1
) && ok "deliver-plan-surfacing" || bad "deliver-plan-surfacing"
rm -rf "$SURF_FIX"

if [[ "$FAIL" -eq 0 ]]; then
  echo "pilot fixtures: all passed"
  exit 0
fi
echo "pilot fixtures: $FAIL failure(s)"
exit 1

"""

if __name__ == "__main__":
    raise SystemExit(main())
