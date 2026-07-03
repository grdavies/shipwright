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

from _sw.vendor_paths import repo_root
from unit_tests._harness_runtime import harness_subprocess_env as _harness_env
from unit_tests._harness_runtime import patch_source as _patch_source


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
# PRD 036 R6–R8: regression remediation routing fixtures (offline).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOOP_PY="$ROOT/scripts/wave_deliver_loop.py"
FAIL=0

ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

# --- verify-failed-routes-bounded-stabilize (R6) ---
ROUTE_FIX=$(mktemp -d "${TMPDIR:-/tmp}/sw-regression-route.XXXXXX")
(
  cd "$ROUTE_FIX"
  git init -q && git config user.email test@test.com && git config user.name Test
  git commit --allow-empty -q -m init
  mkdir -p .cursor/sw-deliver-runs scripts
  cp "$ROOT/scripts/"*.py scripts/
  cp "$ROOT/scripts/wave.sh" scripts/ && chmod +x scripts/wave.sh
  echo '{"deliver":{"remediation":{"maxAttempts":2}}}' >.cursor/workflow.config.json
  echo '{"mode":"phase","target":{"branch":"feat/demo","slug":"demo"},"items":[{"id":"1","slug":"alpha","branch":"feat/demo-phase-alpha"}],"waves":[["1"]],"edges":[]}' \
    >.cursor/sw-deliver-plan.json
  python3 -c "
import json
from pathlib import Path
state = {
  'verdict': 'running',
  'target': {'branch': 'feat/demo', 'slug': 'demo'},
  'nextAction': 'merge-run-next',
  'currentWave': 1,
  'baseCapture': {'branch': 'main', 'sha': 'abc'},
  'waveBatchingPlan': {'waves': [['1']]},
  'mergeQueue': [{'phaseSlug': 'alpha', 'head': 'abc', 'pr': 1}],
  'phases': {'1': {'slug': 'alpha', 'status': 'in-flight', 'branch': 'feat/demo-phase-alpha'}},
  'orchestratorWorktree': {'path': str(Path('.').resolve())},
}
open('.cursor/sw-deliver-state.demo.json','w').write(json.dumps(state, indent=2))
"
  if OUT=$(python3 -c "
import json, sys
from pathlib import Path
sys.path.insert(0, 'scripts')
import wave_deliver_loop as wdl

root = Path('.')
state = json.load(open('.cursor/sw-deliver-state.demo.json'))
plan = json.load(open('.cursor/sw-deliver-plan.json'))

def fake_run_wave(r, *args):
    st = wdl.load_state(r)
    for pid, meta in (st.get('phases') or {}).items():
        if isinstance(meta, dict) and meta.get('slug') == 'alpha':
            meta['status'] = 'blocked'
            meta['cause'] = 'verify:failed'
            wdl._record_remediation_cause(meta, 'verify:failed')
            meta['lastRemediationAt'] = wdl.utc_now()
    wdl.save_state(r, st)
    return 20, {
        'cause': 'verify:failed',
        'phase': 'alpha',
        'halt': 'blocked',
        'recommendedCommand': '/sw-stabilize',
    }

orig = wdl.run_wave
wdl.run_wave = fake_run_wave
try:
    result = wdl.execute_mechanical(root, state, plan, {'action': 'merge-run-next'})
    st = wdl.load_state(root)
finally:
    wdl.run_wave = orig
print(json.dumps({'result': result, 'nextAction': st.get('nextAction')}))
" 2>/dev/null) && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
r=d['result']
assert r.get('executed')=='merge-run-next'
assert r.get('verifyFailed') is True
assert d.get('nextAction')=='remediate'
"; then
    :
  else
    exit 1
  fi
  if OUT=$(python3 "$LOOP_PY" "$ROUTE_FIX" compute-next 2>/dev/null) && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['next']['action']=='remediate'
"; then
    :
  else
    exit 1
  fi
) && ok "verify-failed-routes-bounded-stabilize" || bad "verify-failed-routes-bounded-stabilize"
rm -rf "$ROUTE_FIX"

# --- blocked-budget-signature-distinct (R7) ---
if python3 -c "
import sys
sys.path.insert(0, '$ROOT/scripts')
import wave_deliver_loop as wdl

inflight = {
  'verdict': 'running', 'nextAction': 'merge-run-next', 'currentWave': 1,
  'phases': {'1': {'slug': 'alpha', 'status': 'in-flight'}},
  'mergeQueue': [], 'mergeJournal': None,
}
blocked = {
  'verdict': 'running', 'nextAction': 'remediate', 'currentWave': 1,
  'phases': {'1': {'slug': 'alpha', 'status': 'blocked', 'cause': 'verify:failed', 'lastRemediationAt': '2026-06-29T00:00:00Z'}},
  'remediationAttempts': {}, 'mergeQueue': [], 'mergeJournal': None,
}
assert wdl.build_state_signature(inflight) != wdl.build_state_signature(blocked)
"; then
  ok "blocked-budget-signature-distinct"
else
  bad "blocked-budget-signature-distinct"
fi

# --- remediation-exhaustion-consolidated-halt (R8) ---
HALT_FIX=$(mktemp -d "${TMPDIR:-/tmp}/sw-regression-halt.XXXXXX")
(
  cd "$HALT_FIX"
  git init -q && git config user.email test@test.com && git config user.name Test
  git commit --allow-empty -q -m init
  mkdir -p .cursor/sw-deliver-runs scripts
  cp "$ROOT/scripts/"*.py scripts/
  cp "$ROOT/scripts/wave.sh" scripts/ && chmod +x scripts/wave.sh
  echo '{"deliver":{"remediation":{"maxAttempts":2}}}' >.cursor/workflow.config.json
  echo '{"mode":"phase","target":{"branch":"feat/demo","slug":"demo"},"items":[{"id":"1","slug":"alpha","branch":"feat/demo-phase-alpha"}],"waves":[["1"]],"edges":[]}' \
    >.cursor/sw-deliver-plan.json
  python3 -c "
import json
from pathlib import Path
state = {
  'verdict': 'running',
  'target': {'branch': 'feat/demo', 'slug': 'demo'},
  'source_task_list': 'docs/prds/036-demo/tasks.md',
  'nextAction': 'remediate',
  'currentWave': 1,
  'baseCapture': {'branch': 'main', 'sha': 'abc'},
  'waveBatchingPlan': {'waves': [['1']]},
  'remediationAttempts': {'1': 2},
  'phases': {'1': {'slug': 'alpha', 'status': 'blocked', 'cause': 'verify:failed', 'branch': 'feat/demo-phase-alpha'}},
  'orchestratorWorktree': {'path': str(Path('.').resolve())},
}
open('.cursor/sw-deliver-state.demo.json','w').write(json.dumps(state, indent=2))
"
  if OUT=$(python3 "$LOOP_PY" "$HALT_FIX" deliver-loop --max-steps 1 2>/dev/null || true) && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('halt') is True
assert d.get('cause')=='remediation-budget-exhausted'
"; then
    :
  else
    echo "$OUT"
    exit 1
  fi
  if python3 -c "
import json
b=json.load(open('.cursor/sw-deliver-runs/blockers.json'))
assert b.get('resumeCommand','').startswith('/sw-deliver run')
"; then
    :
  else
    exit 1
  fi
) && ok "remediation-exhaustion-consolidated-halt" || bad "remediation-exhaustion-consolidated-halt"
rm -rf "$HALT_FIX"

if [ "$FAIL" -ne 0 ]; then
  echo "regression-remediation fixtures: FAIL"
  exit 1
fi
echo "regression-remediation fixtures: PASS"
exit 0

"""

if __name__ == "__main__":
    raise SystemExit(main())
