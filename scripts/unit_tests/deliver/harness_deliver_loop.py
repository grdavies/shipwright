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
git branch -M main
mkdir -p .cursor
cat >.cursor/workflow.config.json <<'WCFG'
{"review":{"provider":"none"},"checks":{"treatNeutralAsPass":true}}
WCFG
cat >.cursor/sw-base-state.json <<'JSON'
{"trunkBase": {"name": "main", "sha": "deadbeef00000000000000000000000000000000"}}
JSON

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
assert n.get('action') in ('base-capture','dispatch-ship','collect-status','merge-enqueue','provision-phase','remediate')
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
if ! grep -qE 'Next steps' "$ROOT/core/commands/sw-deliver.md" && \
   ! grep -qE 'cd <worktree>' "$ROOT/core/commands/sw-deliver.md" && \
   grep -qE 'deliver-loop' "$ROOT/core/commands/sw-deliver.md" && \
   grep -qE 'deliver-loop' "$ROOT/core/skills/deliver/SKILL.md" && \
   grep -qE 'deliver-loop' "$ROOT/core/commands/sw-doc.md"; then
  ok "deliver-loop-no-manual-handoff: docs wire deliver-loop not prose handoff"
else
  bad "deliver-loop-no-manual-handoff"
fi

# --- deliver-advance-from-status-only (R7) ---
for _scoped in .cursor/sw-deliver-state.*.json; do
  [[ -e "$_scoped" && "$(basename "$_scoped")" != "sw-deliver-state.json" ]] && rm -f "$_scoped"
done
cat >.cursor/sw-deliver-state.json <<JSON
{
  "verdict": "running",
  "target": {"type": "feat", "slug": "demo", "branch": "feat/demo"},
  "source_task_list": "docs/prds/007-x/tasks.md",
  "currentWave": 1,
  "nextAction": "dispatch-ship",
  "driverHeartbeatAt": "$NOW_TS",
  "orchestratorWorktree": {"path": "/tmp/orch"},
  "specSeed": {"skipped": true},
  "phases": {
    "1": {"id": "1", "slug": "alpha", "status": "in-flight", "startedAt": "$NOW_TS"},
    "2": {"id": "2", "slug": "beta", "status": "pending"}
  }
}
JSON
STATUS_DIR="$FIX/.cursor/sw-deliver-runs/alpha"
mkdir -p "$STATUS_DIR"
PHASE_HEAD=$(git -C "$FIX" rev-parse HEAD 2>/dev/null || echo abc)
git -C "$FIX" branch feat/demo-phase-alpha "$PHASE_HEAD" 2>/dev/null || true
"$ROOT/scripts/ship-phase-status.sh" --verdict merge-ready-green --phase alpha --head "$PHASE_HEAD" --out "$STATUS_DIR/status.json" >/dev/null
python3 -c "
import json
from pathlib import Path
s=json.loads(Path('.cursor/sw-deliver-state.json').read_text())
s['phases']['1']['status']='in-flight'
s['phases']['1']['branch']='feat/demo-phase-alpha'
s['phaseWorktrees']={'1': {'path': '$FIX', 'name': 'alpha-wt'}}
s['baseCapture']={'skipped': True}
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
for _scoped in .cursor/sw-deliver-state.*.json; do
  [[ -e "$_scoped" && "$(basename "$_scoped")" != "sw-deliver-state.json" ]] && rm -f "$_scoped"
done
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
for _scoped in .cursor/sw-deliver-state.*.json; do
  [[ -e "$_scoped" && "$(basename "$_scoped")" != "sw-deliver-state.json" ]] && rm -f "$_scoped"
done
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
if OUT=$(python3 "$LOOP_PY" "$FIX" deliver-loop --task-list docs/prds/007-x/tasks.md --max-steps 1 2>&1 || true) && echo "$OUT" | grep -qE 'stale run-state'; then
  ok "stale-state-refuses-start"
else
  bad "stale-state-refuses-start"
fi

# --- PRD 009 pilot: conductor contract single source (R1/R3/R34) ---
if [[ -f "$ROOT/core/skills/conductor/SKILL.md" ]] && \
   [[ -f "$ROOT/core/rules/sw-conductor.mdc" ]] && \
   grep -qE 'skills/conductor/SKILL.md' "$ROOT/core/commands/sw-deliver.md" && \
   grep -qE 'skills/conductor/SKILL.md' "$ROOT/core/skills/deliver/SKILL.md"; then
  ok "conductor-contract-single-source"
else
  bad "conductor-contract-single-source"
fi

# --- PRD 009 pilot: parallel wave peak concurrency >= 2 (R14/R34) ---
PAR_PLAN="$FIX/.cursor/sw-deliver-plan-parallel.json"
cat >"$PAR_PLAN" <<'JSON'
{
  "verdict": "pass",
  "mode": "phase",
  "waves": [["1", "2", "3"]],
  "items": [
    {"id": "1", "slug": "a"},
    {"id": "2", "slug": "b"},
    {"id": "3", "slug": "c"}
  ]
}
JSON
if OUT=$(python3 "$ROOT/scripts/wave_deliver.py" "$FIX" schedule --plan .cursor/sw-deliver-plan-parallel.json --ceiling 4 2>/dev/null) && \
   echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
peak=max(b['slotCount'] for w in d['schedule'] for b in w['batches'])
assert peak >= 2, peak
"; then
  ok "deliver-pilot-parallel-wave-peak-concurrency"
else
  bad "deliver-pilot-parallel-wave-peak-concurrency"
fi

# --- PRD 009 surface docs (R36) ---
if grep -qE 'Legitimate.halt|legitimate.halt|legitimate halt' "$ROOT/core/commands/sw-deliver.md" && \
   grep -qE 'parallel' "$ROOT/docs/guides/workflows.md" && \
   grep -qE 'deliver.autonomy' "$ROOT/core/commands/sw-deliver.md"; then
  ok "deliver-surface-docs-autonomy-parallelism"
else
  bad "deliver-surface-docs-autonomy-parallelism"
fi

# --- PRD 013 A1 terminal autonomy (R20–R24) ---
TERM_PY="$ROOT/scripts/wave_terminal.py"
DEFAULT_CFG_FIX=$(mktemp -d)
mkdir -p "$DEFAULT_CFG_FIX/.cursor"
echo '{}' >"$DEFAULT_CFG_FIX/.cursor/workflow.config.json"
if OUT=$(python3 "$TERM_PY" "$DEFAULT_CFG_FIX" terminal autonomy 2>/dev/null) && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('mode')=='supervised'
assert d.get('supervisedHalts') is True
"; then
  ok "deliver-terminal-autonomy-knob: default supervised"
else
  bad "deliver-terminal-autonomy-knob: default supervised"
fi
rm -rf "$DEFAULT_CFG_FIX"

AUTO_CFG_FIX=$(mktemp -d)
mkdir -p "$AUTO_CFG_FIX/.cursor"
cp "$ROOT/.cursor/workflow.config.json" "$AUTO_CFG_FIX/.cursor/" 2>/dev/null || echo '{}' >"$AUTO_CFG_FIX/.cursor/workflow.config.json"
python3 -c "
import json
from pathlib import Path
p=Path('$AUTO_CFG_FIX/.cursor/workflow.config.json')
cfg=json.loads(p.read_text())
cfg.setdefault('deliver',{})['terminal']={'autonomy':'auto'}
p.write_text(json.dumps(cfg, indent=2))
"
if OUT=$(python3 "$TERM_PY" "$AUTO_CFG_FIX" terminal autonomy 2>/dev/null) && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('mode')=='auto' and d.get('handsOff')
"; then
  ok "deliver-terminal-autonomy-knob: auto mode honored"
else
  bad "deliver-terminal-autonomy-knob: auto mode honored"
fi
rm -rf "$AUTO_CFG_FIX"

RETRO_FIX=$(mktemp -d)
(
  cd "$RETRO_FIX"
  git init -q
  git config user.email t@t.com
  git config user.name T
  git commit --allow-empty -q -m init
  git branch -M main
  git checkout -qb feat/terminal-retro
  git commit --allow-empty -q -m feat
  mkdir -p .cursor docs/prds
  cat >.cursor/workflow.config.json <<'JSON'
{"defaultBaseBranch":"main","deliver":{"terminal":{"autonomy":"auto"}}}
JSON
  cat >.cursor/sw-deliver-state.terminal-retro.json <<'JSON'
{"verdict":"running","prd_number":"013","target":{"branch":"feat/terminal-retro"},"phases":{"1":{"status":"green-merged","slug":"a"},"2":{"status":"green-merged","slug":"b"}}}
JSON
  if OUT=$(python3 "$TERM_PY" "$RETRO_FIX" terminal retro run --dry-run 2>/dev/null) && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('action')=='terminal-retro-run'
assert d.get('targetBranch')=='feat/terminal-retro'
assert d.get('wouldCommitOn')=='feat/terminal-retro'
"; then
    :
  else
    exit 1
  fi
) && ok "deliver-terminal-retro-before-pr" || bad "deliver-terminal-retro-before-pr"
rm -rf "$RETRO_FIX"

if OUT=$(python3 "$TERM_PY" "$ROOT" terminal ship run --dry-run --force 2>/dev/null) && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('neverAutoMergesMain') is True
assert 'gate-watch' in d.get('steps',[])
"; then
  ok "deliver-terminal-no-auto-merge: dry-run declares human gate"
else
  SHIP_FIX=$(mktemp -d)
  cd "$SHIP_FIX"
  git init -q
  git config user.email t@t.com
  git config user.name T
  git commit --allow-empty -q -m init
  git branch -M main
  git checkout -qb feat/terminal-ship
  mkdir -p .cursor
  echo '{"defaultBaseBranch":"main","deliver":{"terminal":{"autonomy":"auto"}}}' > .cursor/workflow.config.json
  echo '{"verdict":"running","prd_number":"013","target":{"branch":"feat/terminal-ship"},"phases":{"1":{"status":"green-merged","slug":"a"}},"compoundShip":{"premergeDone":true}}' > .cursor/sw-deliver-state.terminal-ship.json
  if OUT2=$(python3 "$TERM_PY" "$SHIP_FIX" terminal ship run --dry-run 2>/dev/null) && echo "$OUT2" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('neverAutoMergesMain') is True
"; then
    ok "deliver-terminal-no-auto-merge: dry-run declares human gate"
  else
    bad "deliver-terminal-no-auto-merge"
  fi
  rm -rf "$SHIP_FIX"
fi

# --- PRD 017 Phase 2: parallel-batch-driver (R22) ---
BATCH_FIX=$(mktemp -d)
(
  cd "$BATCH_FIX"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  git commit --allow-empty -q -m init
  mkdir -p .cursor
  cat >.cursor/sw-base-state.json <<'JSON'
{"trunkBase": {"name": "main", "sha": "deadbeef00000000000000000000000000000000"}}
JSON
  cat >.cursor/sw-deliver-plan.json <<'JSON'
{
  "verdict": "pass",
  "mode": "phase",
  "target": {"type": "feat", "slug": "batch", "branch": "feat/batch"},
  "items": [
    {"id": "1", "slug": "a", "branch": "feat/batch-phase-a"},
    {"id": "2", "slug": "b", "branch": "feat/batch-phase-b"},
    {"id": "3", "slug": "c", "branch": "feat/batch-phase-c"}
  ],
  "edges": [],
  "waves": [["1", "2", "3"]]
}
JSON
  cat >.cursor/sw-base-state.json <<'JSON'
{"trunkBase": {"name": "main", "sha": "deadbeef00000000000000000000000000000000"}}
JSON
  NOW_TS=$(python3 -c "from datetime import datetime,timezone; print(datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))")
  cat >.cursor/sw-deliver-state.json <<JSON
{
  "verdict": "running",
  "target": {"branch": "feat/batch"},
  "currentWave": 1,
  "specSeed": {"skipped": true},
  "baseCapture": {"skipped": true},
  "orchestratorWorktree": {"path": "/tmp/orch"},
  "driverHeartbeatAt": "$NOW_TS",
  "phases": {
    "1": {"id": "1", "slug": "a", "status": "pending"},
    "2": {"id": "2", "slug": "b", "status": "pending"},
    "3": {"id": "3", "slug": "c", "status": "pending"}
  },
  "phaseWorktrees": {
    "1": {"path": "/tmp/a", "name": "a"},
    "2": {"path": "/tmp/b", "name": "b"},
    "3": {"path": "/tmp/c", "name": "c"}
  }
}
JSON
  echo '{"worktree":{"parallelCeiling":4}}' >.cursor/workflow.config.json
  if OUT=$(python3 "$LOOP_PY" "$BATCH_FIX" compute-next 2>/dev/null) && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
n=d['next']
assert n['action']=='dispatch-batch', n
assert len(n.get('phaseIds',[]))>=2, n
for pid in n['phaseIds']:
    assert pid in ('1','2','3')
"; then
    :
  else
    exit 1
  fi
) && ok "parallel-batch-driver" || bad "parallel-batch-driver"
rm -rf "$BATCH_FIX"

# --- PRD 017 Phase 2: deliver-resume-command-is-sw (R29) ---
if python3 - <<'PY' "$ROOT"
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "scripts"))
from wave_failure import resume_deliver_command
cmd = resume_deliver_command({"source_task_list": "docs/prds/017-x/tasks.md"})
assert cmd.startswith("/sw-deliver run "), cmd
assert "bash" not in cmd, cmd
assert resume_deliver_command({}) == "/sw-deliver run"
PY
then
  ok "deliver-resume-command-is-sw"
else
  bad "deliver-resume-command-is-sw"
fi

# --- PRD 017 Phase 2: parallel-collect-all-ready (R27) stub ---
COLLECT_FIX=$(mktemp -d)
(
  cd "$COLLECT_FIX"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  git commit --allow-empty -q -m init
  git branch -M main
  git branch feat/collect-phase-a
  git branch feat/collect-phase-b
  mkdir -p .cursor .cursor/sw-deliver-runs/a .cursor/sw-deliver-runs/b
  cat >.cursor/workflow.config.json <<'WCFG'
{"review":{"provider":"none"},"checks":{"treatNeutralAsPass":true}}
WCFG
  cat >.cursor/sw-base-state.json <<'JSON'
{"trunkBase": {"name": "main", "sha": "deadbeef00000000000000000000000000000000"}}
JSON
  NOW_TS=$(python3 -c "from datetime import datetime,timezone; print(datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))")
  HEAD=$(git rev-parse HEAD)
  cat >.cursor/sw-deliver-state.json <<JSON
{
  "verdict": "running",
  "target": {"branch": "feat/collect"},
  "currentWave": 1,
  "specSeed": {"skipped": true},
  "baseCapture": {"skipped": true},
  "orchestratorWorktree": {"path": "/tmp/orch"},
  "driverHeartbeatAt": "$NOW_TS",
  "phases": {
    "2": {"id": "2", "slug": "b", "status": "in-flight", "branch": "feat/collect-phase-b"},
    "1": {"id": "1", "slug": "a", "status": "in-flight", "branch": "feat/collect-phase-a"}
  },
  "phaseWorktrees": {
    "1": {"path": "$COLLECT_FIX", "name": "a"},
    "2": {"path": "$COLLECT_FIX", "name": "b"}
  }
}
JSON
  cat >.cursor/sw-deliver-plan.json <<'JSON'
{
  "mode": "phase",
  "target": {"branch": "feat/collect"},
  "items": [
    {"id": "1", "slug": "a", "branch": "feat/collect-phase-a"},
    {"id": "2", "slug": "b", "branch": "feat/collect-phase-b"}
  ],
  "edges": [],
  "waves": [["1", "2"]]
}
JSON
  "$ROOT/scripts/ship-phase-status.sh" --verdict merge-ready-green --phase a --head "$HEAD" --out .cursor/sw-deliver-runs/a/status.json >/dev/null
  "$ROOT/scripts/ship-phase-status.sh" --verdict merge-ready-green --phase b --head "$HEAD" --out .cursor/sw-deliver-runs/b/status.json >/dev/null
  if OUT=$(python3 "$LOOP_PY" "$COLLECT_FIX" compute-next 2>/dev/null) && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
n=d['next']
assert n['action']=='collect-all-ready', n
slugs=[p['phaseSlug'] for p in n['phases']]
assert slugs==['a','b'], slugs
"; then
    :
  else
    exit 1
  fi
) && ok "parallel-collect-all-ready" || bad "parallel-collect-all-ready"
rm -rf "$COLLECT_FIX"

# --- PRD 017 Phase 2: parallel-background-task-failure (R27) stub ---
BG_FIX=$(mktemp -d)
(
  cd "$BG_FIX"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  git commit --allow-empty -q -m init
  mkdir -p .cursor
  cat >.cursor/sw-base-state.json <<'JSON'
{"trunkBase": {"name": "main", "sha": "deadbeef00000000000000000000000000000000000000"}}
JSON
  NOW_TS=$(python3 -c "from datetime import datetime,timezone; print(datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))")
  cat >.cursor/sw-deliver-state.json <<JSON
{
  "verdict": "running",
  "target": {"branch": "feat/bg"},
  "currentWave": 1,
  "specSeed": {"skipped": true},
  "baseCapture": {"skipped": true},
  "orchestratorWorktree": {"path": "/tmp/orch"},
  "driverHeartbeatAt": "$NOW_TS",
  "phases": {
    "1": {
      "id": "1",
      "slug": "a",
      "status": "in-flight",
      "backgroundDispatchedAt": "2020-01-01T00:00:00Z"
    }
  }
}
JSON
  cat >.cursor/sw-deliver-plan.json <<'JSON'
{"mode":"phase","target":{"branch":"feat/bg"},"items":[{"id":"1","slug":"a"}],"edges":[],"waves":[["1"]]}
JSON
  echo '{"deliver":{"watchdog":{"backgroundTaskTimeoutMinutes":1}}}' >.cursor/workflow.config.json
  if OUT=$(python3 "$LOOP_PY" "$BG_FIX" compute-next 2>/dev/null) && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['next']['action']=='halt-blocked'
assert 'background-task-timeout' in d['next'].get('cause','')
"; then
    :
  else
    exit 1
  fi
) && ok "parallel-background-task-failure" || bad "parallel-background-task-failure"
rm -rf "$BG_FIX"

# --- budget-proposed-overhead-accounted (PRD 023 R22) ---
BUDGET_FIX=$(mktemp -d)
(
  cd "$BUDGET_FIX"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  git commit --allow-empty -q -m init
  mkdir -p .cursor
  echo '{"deliver":{"autonomy":{"maxIterations":2}}}' >.cursor/workflow.config.json
  echo '{"verdict":"running","target":{"branch":"feat/demo"},"nextAction":"wave-plan-persist","currentWave":1,"phases":{"1":{"slug":"alpha","status":"pending"}},"orchestratorWorktree":{"path":"/tmp/orch"}}' \
    >.cursor/sw-deliver-state.json
  cp "$ROOT/.cursor/sw-deliver-plan.json" .cursor/sw-deliver-plan.json 2>/dev/null || \
    echo '{"mode":"phase","target":{"branch":"feat/demo"},"items":[{"id":"1","slug":"alpha"}],"waves":[["1"]],"edges":[]}' >.cursor/sw-deliver-plan.json
  for _ in 1 2 3 4; do
    python3 "$LOOP_PY" "$BUDGET_FIX" budget-tick --next-action wave-plan-persist >/dev/null
  done
  if python3 "$LOOP_PY" "$BUDGET_FIX" budget-check 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['verdict']=='pass'
assert d['budgetCounters']['proposalOverheadCount']==4
assert d['budgetCounters']['executionIterationCount']==0
"; then
    :
  else
    exit 1
  fi
) && ok "budget-proposed-overhead-accounted" || bad "budget-proposed-overhead-accounted"
rm -rf "$BUDGET_FIX"

# --- budget-halt-merge-queue-integrity (PRD 023 R22) ---
HALT_FIX=$(mktemp -d)
(
  cd "$HALT_FIX"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  git commit --allow-empty -q -m init
  mkdir -p .cursor
  echo '{"deliver":{"autonomy":{"maxIterations":1}}}' >.cursor/workflow.config.json
  cat >.cursor/sw-deliver-plan.json <<'JSON'
{"mode":"phase","target":{"branch":"feat/demo"},"items":[{"id":"1","slug":"alpha","branch":"feat/demo-phase-alpha"}],"waves":[["1"]],"edges":[]}
JSON
  cat >.cursor/sw-deliver-state.demo.json <<'JSON'
{
  "verdict": "running",
  "target": {"branch": "feat/demo"},
  "nextAction": "merge-run-next",
  "currentWave": 1,
  "driverIterationCount": 0,
  "budgetCounters": {"proposalOverheadCount": 0, "executionIterationCount": 1},
  "noProgressStreak": 0,
  "orchestratorWorktree": {"path": "/tmp/orch"},
  "mergeQueue": [{"phaseSlug": "alpha", "head": "abc123"}],
  "mergeJournal": {"phase": "alpha", "head": "abc123", "startedAt": "2026-01-01T00:00:00Z", "key": "alpha"},
  "phases": {"1": {"slug": "alpha", "status": "in-flight", "branch": "feat/demo-phase-alpha"}}
}
JSON
  echo '{"target":"feat/demo","holder":"test","pid":1,"at":"2026-01-01T00:00:00Z"}' >.cursor/sw-deliver-demo.lock
  if OUT=$(python3 "$LOOP_PY" "$HALT_FIX" compute-next 2>/dev/null) && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['next']['action']=='halt-blocked'
assert d['next'].get('budgetHalt') is True
"; then
    :
  else
    exit 1
  fi
  if OUT=$(python3 "$LOOP_PY" "$HALT_FIX" deliver-loop --max-steps 1 2>/dev/null || true) && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('halt') is True
assert d.get('cause','').startswith('conductor:')
"; then
    :
  else
    exit 1
  fi
  if test ! -f .cursor/sw-deliver-demo.lock && \
     python3 -c "
import json
s=json.load(open('.cursor/sw-deliver-state.demo.json'))
assert s.get('mergeJournal') is None
assert len(s.get('mergeQueue') or []) >= 1
"; then
    :
  else
    exit 1
  fi
) && ok "budget-halt-merge-queue-integrity" || bad "budget-halt-merge-queue-integrity"
rm -rf "$HALT_FIX"

# --- plan-rejection-no-progress (PRD 023 R22 / 022 R6) ---
REJ_FIX=$(mktemp -d)
(
  cd "$REJ_FIX"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  git commit --allow-empty -q -m init
  mkdir -p .cursor
  cat >.cursor/sw-deliver-state.json <<'JSON'
{
  "verdict": "running",
  "target": {"branch": "feat/demo"},
  "nextAction": "provision-phase",
  "currentWave": 1,
  "planRejectionLog": {
    "version": 1,
    "threshold": 3,
    "phases": {"1": {"consecutiveRejections": 3, "entries": []}},
    "halt": {"cause": "plan-rejection-breaker", "phaseId": "1", "consecutiveRejections": 3}
  },
  "phases": {"1": {"slug": "alpha", "status": "pending"}},
  "orchestratorWorktree": {"path": "/tmp/orch"}
}
JSON
  echo '{"mode":"phase","target":{"branch":"feat/demo"},"items":[{"id":"1","slug":"alpha"}],"waves":[["1"]],"edges":[]}' >.cursor/sw-deliver-plan.json
  if python3 "$LOOP_PY" "$REJ_FIX" compute-next 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['next']['action']=='halt-blocked'
assert 'plan-rejection' in d['next'].get('cause','')
"; then
    :
  else
    exit 1
  fi
) && ok "plan-rejection-no-progress" || bad "plan-rejection-no-progress"
rm -rf "$REJ_FIX"

if [[ "$FAIL" -ne 0 ]]; then
  echo "deliver-loop fixtures: FAIL"
  exit 1
fi
echo "deliver-loop fixtures: PASS"

"""
