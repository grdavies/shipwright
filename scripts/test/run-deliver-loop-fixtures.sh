#!/usr/bin/env bash
# Fixtures for deliver-loop driver (PRD 007 Phase 3 — R1–R12, R46).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOOP_PY="$ROOT/scripts/wave_deliver_loop.py"
WAVE="$ROOT/scripts/wave.sh"
FAIL=0

ok()   { echo "OK  $1"; }
bad()  { echo "FAIL $1"; FAIL=1; }

FIX=$(mktemp -d)
trap 'rm -rf "$FIX"' EXIT

cd "$FIX"
git init -q
git config user.email test@test.com
git config user.name Test
git commit --allow-empty -q -m init
mkdir -p .cursor

# Minimal phase-mode plan + in-progress state (resume scenario)
cat >.cursor/sw-deliver-plan.json <<'JSON'
{
  "verdict": "pass",
  "mode": "phase",
  "source_task_list": "docs/prds/007-x/tasks.md",
  "target": {"type": "feat", "slug": "demo", "branch": "feat/demo"},
  "items": [
    {"id": "1", "slug": "alpha", "title": "Alpha", "branch": "feat/demo-phase-alpha"},
    {"id": "2", "slug": "beta", "title": "Beta", "branch": "feat/demo-phase-beta"}
  ],
  "edges": [{"from": "1", "to": "2"}],
  "waves": [["1"], ["2"]]
}
JSON

NOW_TS=$(python3 -c "from datetime import datetime,timezone; print(datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))")

cat >.cursor/sw-deliver-state.json <<JSON
{
  "verdict": "running",
  "target": {"type": "feat", "slug": "demo", "branch": "feat/demo"},
  "source_task_list": "docs/prds/007-x/tasks.md",
  "currentWave": 1,
  "nextAction": "dispatch-ship",
  "remediationAttempts": {},
  "driverHeartbeatAt": "$NOW_TS",
  "orchestratorWorktree": {"path": "/tmp/orch", "name": "demo-orchestrator"},
  "phases": {
    "1": {"id": "1", "slug": "alpha", "status": "in-flight", "startedAt": "$NOW_TS"},
    "2": {"id": "2", "slug": "beta", "status": "pending"}
  },
  "phaseWorktrees": {"1": {"name": "demo-phase-alpha", "path": "/tmp/phase-alpha"}}
}
JSON

# --- deliver-loop-resume-from-state ---
if OUT=$(python3 "$LOOP_PY" "$FIX" deliver-loop --dry-run 2>/dev/null) && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('resumed') is True
n=d['next']
assert n.get('action') in ('dispatch-ship','collect-status','merge-enqueue','provision-phase','remediate')
assert n.get('resume') is True
"; then
  ok "deliver-loop-resume-from-state: dry-run resumes from durable state"
else
  bad "deliver-loop-resume-from-state"
fi

# Fresh compute-next should not restart at plan when state present
if python3 "$LOOP_PY" "$FIX" compute-next 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['next']['action'] != 'plan'
"; then
  ok "deliver-loop-resume-from-state: compute-next skips plan"
else
  bad "deliver-loop-resume-from-state: compute-next skips plan"
fi

# --- deliver-loop-no-manual-handoff ---
if ! rg -q 'Next steps' "$ROOT/core/commands/sw-deliver.md" && \
   ! rg -q 'cd <worktree>' "$ROOT/core/commands/sw-deliver.md" && \
   rg -q 'deliver-loop' "$ROOT/core/commands/sw-deliver.md" && \
   rg -q 'deliver-loop' "$ROOT/core/skills/deliver/SKILL.md" && \
   rg -q 'deliver-loop' "$ROOT/core/commands/sw-doc.md"; then
  ok "deliver-loop-no-manual-handoff: docs wire deliver-loop not prose handoff"
else
  bad "deliver-loop-no-manual-handoff"
fi

# --- deliver-advance-from-status-only (R7) ---
STATUS_DIR="$FIX/.cursor/sw-deliver-runs/alpha"
mkdir -p "$STATUS_DIR"
PHASE_HEAD=$(git -C "$FIX" rev-parse HEAD 2>/dev/null || echo abc)
cat >"$STATUS_DIR/status.json" <<JSON
{"verdict":"merge-ready-green","phase":"alpha","head":"$PHASE_HEAD","gate":{"verdict":"green"}}
JSON
python3 -c "
import json
from pathlib import Path
s=json.loads(Path('.cursor/sw-deliver-state.json').read_text())
s['phases']['1']['status']='in-flight'
s['phases']['1']['branch']='feat/demo-phase-alpha'
s['phaseWorktrees']={'1': {'path': '$FIX', 'name': 'alpha-wt'}}
s.pop('source_task_list', None)
Path('.cursor/sw-deliver-state.json').write_text(json.dumps(s))
"
mv .cursor/sw-deliver-plan.json .cursor/sw-deliver-plan.json.advance-bak
python3 -c "
import json
from pathlib import Path
p=json.loads(Path('.cursor/sw-deliver-plan.json.advance-bak').read_text())
p.pop('source_task_list', None)
Path('.cursor/sw-deliver-plan.json').write_text(json.dumps(p))
"
if OUT=$(python3 "$LOOP_PY" "$FIX" compute-next 2>/dev/null) && \
   echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['next']['action']=='merge-enqueue', d
"; then
  ok "deliver-advance-from-status-only: merge-ready status drives enqueue not chat"
else
  bad "deliver-advance-from-status-only"
fi
mv .cursor/sw-deliver-plan.json.advance-bak .cursor/sw-deliver-plan.json

# --- deliver-remediation-maxattempts-default ---
if python3 "$LOOP_PY" "$FIX" remediation-default 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['maxAttempts']==2
assert d['default']==2
"; then
  ok "deliver-remediation-maxattempts-default: absent key defaults to 2"
else
  bad "deliver-remediation-maxattempts-default"
fi

echo '{"deliver":{"remediation":{"maxAttempts":5}}}' >.cursor/workflow.config.json
if python3 "$LOOP_PY" "$FIX" remediation-default 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['maxAttempts']==5
"; then
  ok "deliver-remediation-maxattempts-default: config override honored"
else
  bad "deliver-remediation-maxattempts-default: config override"
fi

# --- deliver-blocker-clean-halt ---
rm -f .cursor/workflow.config.json
cat >.cursor/sw-deliver-state.json <<'JSON'
{
  "verdict": "running",
  "target": {"branch": "feat/demo"},
  "currentWave": 1,
  "nextAction": "remediate",
  "remediationAttempts": {"1": 2},
  "driverHeartbeatAt": "$NOW_TS",
  "orchestratorWorktree": {"path": "/tmp/orch"},
  "phases": {
    "1": {"id": "1", "slug": "alpha", "status": "blocked", "cause": "ci-red"},
    "2": {"id": "2", "slug": "beta", "status": "pending"}
  }
}
JSON
cp .cursor/sw-deliver-plan.json .cursor/sw-deliver-plan.json.bak
if OUT=$(python3 "$LOOP_PY" "$FIX" compute-next 2>/dev/null) && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['next']['action']=='halt-blocked'
assert d['next'].get('cause')=='remediation-budget-exhausted'
"; then
  ok "deliver-blocker-clean-halt: remediation budget routes to halt-blocked"
else
  bad "deliver-blocker-clean-halt"
fi

# --- driver-heartbeat-timeout-halt ---
cat >.cursor/sw-deliver-state.json <<'JSON'
{
  "verdict": "running",
  "target": {"branch": "feat/demo"},
  "currentWave": 1,
  "driverHeartbeatAt": "2020-01-01T00:00:00Z",
  "orchestratorWorktree": {"path": "/tmp/orch"},
  "specSeed": {"skipped": true},
  "phases": {"1": {"id": "1", "slug": "alpha", "status": "pending"}}
}
JSON
export SW_DRIVER_STALE_SECONDS=60
if OUT=$(python3 "$LOOP_PY" "$FIX" compute-next 2>/dev/null) && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['next']['action']=='halt-blocked'
assert 'stale' in d['next'].get('cause','')
"; then
  ok "driver-heartbeat-timeout-halt: stale heartbeat → halt-blocked"
else
  bad "driver-heartbeat-timeout-halt"
fi

# wave.sh routes deliver-loop
if bash "$WAVE" deliver-loop --dry-run 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('action')=='deliver-loop'
"; then
  ok "deliver-loop: wave.sh verb wired"
else
  bad "deliver-loop: wave.sh verb wired"
fi

# --- PRD 009 phase 1 reliability (R25–R31) ---
# R27: wave.sh dispatcher forwards subcommand args (no duplicate status/merge/report)
if OUT=$(bash "$WAVE" status collect --phase-slug missing-phase 2>/dev/null || true) && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('verdict')=='fail'
assert d.get('cause')=='phase-status:missing'
"; then
  ok "wave-dispatch-arg-hygiene: status collect reaches collector"
else
  bad "wave-dispatch-arg-hygiene"
fi

# R29: phase status vocabulary guard
mkdir -p .cursor
cat >.cursor/sw-deliver-state.json <<'JSON'
{"phases":{"1":{"id":"1","slug":"a","status":"pending"}}}
JSON
if OUT=$(python3 "$ROOT/scripts/wave_state.py" "$FIX" state phase --id 1 --status bogus 2>/dev/null || true) && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('verdict')=='fail'
assert 'invalid phase status' in d.get('error','')
"; then
  ok "phase-status-vocabulary-guard"
else
  bad "phase-status-vocabulary-guard"
fi

# R30: stale identity refuses start
cat >.cursor/sw-deliver-state.json <<'JSON'
{
  "verdict": "running",
  "source_task_list": "docs/prds/other/tasks.md",
  "phases": {"1": {"id": "1", "slug": "alpha", "status": "pending"}},
  "driverHeartbeatAt": "$NOW_TS"
}
JSON
if OUT=$(python3 "$LOOP_PY" "$FIX" deliver-loop --task-list docs/prds/007-x/tasks.md --max-steps 1 2>&1 || true) && echo "$OUT" | rg -q 'stale run-state'; then
  ok "stale-state-refuses-start"
else
  bad "stale-state-refuses-start"
fi

if [[ "$FAIL" -ne 0 ]]; then
  echo "deliver-loop fixtures: FAIL"
  exit 1
fi
echo "deliver-loop fixtures: PASS"
