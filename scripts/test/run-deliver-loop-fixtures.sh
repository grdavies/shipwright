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

if [[ "$FAIL" -ne 0 ]]; then
  echo "deliver-loop fixtures: FAIL"
  exit 1
fi
echo "deliver-loop fixtures: PASS"
