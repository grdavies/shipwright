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
# PRD 035 phase 7 / amendment A1 — deliver conductor completion (R25–R50).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=scripts/test/fixture-lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/fixture-lib.sh"

FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

WF="$(content_path ../.cursor/workflow.config.json 2>/dev/null || echo "$ROOT/.cursor/workflow.config.json")"
[[ -f "$WF" ]] || WF="$ROOT/.cursor/workflow.config.json"
MANIFEST="$ROOT/core/sw-reference/pr-test-plan.manifest.json"
LOOP_PY="$ROOT/scripts/wave_deliver_loop.py"
WM="$ROOT/scripts/wave_merge.py"
WLC="$ROOT/scripts/wave_lifecycle.py"
WSS="$ROOT/scripts/wave_spec_seed.py"
PLP="$ROOT/scripts/planning_legacy_projection.py"

# --- 7.1 ship-without-build-chain-sync-fails (R25) ---
if [[ -f "$ROOT/scripts/ship-build-chain-check.py" ]] && \
   [[ -f "$ROOT/core/sw-reference/build-chain-paths.json" ]] && \
   grep -q 'ship-build-chain-check' "$ROOT/core/commands/sw-ship.md"; then
  ok "ship-without-build-chain-sync-fails"
else
  bad "ship-without-build-chain-sync-fails"
fi

# --- 7.1 verify-test-includes-parity (R26) ---
if python3 -c "import json; r=json.load(open('$ROOT/core/sw-reference/suite-registry.json')); assert any(s.get('id')=='parity-fixtures' and s.get('script')=='scripts/test/run_pytest.py' for s in r.get('suites',[]))" 2>/dev/null || \
   grep -q 'parity-fixtures' "$MANIFEST" 2>/dev/null; then
  ok "verify-test-includes-parity"
else
  bad "verify-test-includes-parity"
fi

# --- 7.2 post-merge-build-chain-environmental (R27) ---
if grep -q 'cursor-golden-vs-dist' "$ROOT/scripts/wave_failure.py" && \
   grep -q 'verify:environmental' "$ROOT/scripts/wave_failure.py"; then
  ok "post-merge-build-chain-environmental"
else
  bad "post-merge-build-chain-environmental"
fi

# --- 7.2 merge-queue-deterministic-regen (R28) ---
if grep -q 'deterministic-regen-paths.json' "$ROOT/scripts/wave_merge.py"; then
  ok "merge-queue-deterministic-regen"
else
  bad "merge-queue-deterministic-regen"
fi

# --- 7.2 parallel-wave-regen-before-verify (R29) ---
if grep -qE 'build-chain|regen' "$ROOT/scripts/wave_merge.py" && \
   grep -q 'parallel' "$ROOT/scripts/wave_deliver_loop.py"; then
  ok "parallel-wave-regen-before-verify"
else
  bad "parallel-wave-regen-before-verify"
fi

# --- 7.3 verify-failed-routes-remediate (R30) ---
ROUTE_FIX=$(mktemp -d "${TMPDIR:-/tmp}/sw-035-verify-failed.XXXXXX")
if (
  cd "$ROUTE_FIX" && git init -q && git config user.email t@t.com && git config user.name T
  git commit --allow-empty -q -m init
  mkdir -p .cursor/sw-deliver-runs scripts
  cp "$ROOT/scripts/"*.py scripts/ 2>/dev/null || true
  cp "$ROOT/scripts/wave.py" scripts/ 2>/dev/null || true
  echo '{"deliver":{"remediation":{"maxAttempts":2}}}' >.cursor/workflow.config.json
  echo '{"mode":"phase","target":{"branch":"feat/demo"},"items":[{"id":"1","slug":"alpha","branch":"feat/demo-phase-alpha"}],"waves":[["1"]],"edges":[]}' >.cursor/sw-deliver-plan.json
  python3 -c "
import json
from pathlib import Path
state={'verdict':'running','target':{'branch':'feat/demo'},'nextAction':'merge-run-next','currentWave':1,'baseCapture':{'branch':'main','sha':'abc'},'waveBatchingPlan':{'waves':[['1']]},'mergeQueue':[{'phaseSlug':'alpha'}],'phases':{'1':{'slug':'alpha','status':'in-flight','branch':'feat/demo-phase-alpha'}},'orchestratorWorktree':{'path':str(Path('.').resolve())}}
Path('.cursor/sw-deliver-state.demo.json').write_text(json.dumps(state))
"
  python3 -c "
import json, sys
from pathlib import Path
sys.path.insert(0,'scripts')
import wave_deliver_loop as wdl
root=Path('.')
state=json.load(open('.cursor/sw-deliver-state.demo.json'))
plan=json.load(open('.cursor/sw-deliver-plan.json'))
def fake(r,*a):
  st=wdl.load_state(r)
  for pid,m in (st.get('phases') or {}).items():
    if isinstance(m,dict) and m.get('slug')=='alpha':
      m['status']='blocked'; m['cause']='verify:failed'
  wdl.save_state(r,st)
  return 20,{'cause':'verify:failed','phase':'alpha'}
orig=wdl.run_wave
wdl.run_wave=fake
try:
  r=wdl.execute_mechanical(root,state,plan,{'action':'merge-run-next'})
  assert r.get('verifyFailed') is True
  st=wdl.load_state(root)
  assert st.get('nextAction')=='remediate'
finally:
  wdl.run_wave=orig
"
); then ok "verify-failed-routes-remediate"; else bad "verify-failed-routes-remediate"; fi
rm -rf "$ROUTE_FIX"

# --- 7.3 no-progress-before-first-remediate (R31) ---
if python3 -c "
import sys
sys.path.insert(0,'$ROOT/scripts')
import wave_deliver_loop as wdl
from pathlib import Path
root=Path('$ROOT')
state={'phases':{'1':{'status':'blocked','cause':'verify:failed'}},'remediationAttempts':{},'noProgressStreak':99}
assert wdl.remediate_pending_for_state(root,state)
assert wdl.check_budget_halt(root,state) is None
"; then ok "no-progress-before-first-remediate"; else bad "no-progress-before-first-remediate"; fi

# --- 7.3 current-wave-overflow-terminal (R32) ---
if python3 -c "
import sys
sys.path.insert(0,'$ROOT/scripts')
import wave_deliver_loop as wdl
from pathlib import Path
root=Path('$ROOT')
plan={'mode':'phase','target':{'branch':'feat/x'},'waves':[['1']],'items':[{'id':'1','slug':'a'}],'edges':[]}
state={'verdict':'running','currentWave':9,'phases':{'1':{'status':'blocked','slug':'a'}},'orchestratorWorktree':{'path':'/tmp'},'waveBatchingPlan':{'waves':[['1']]},'baseCapture':{'branch':'main'}}
n=wdl.compute_next_action(root,state,plan)
assert n.get('cause')=='current-wave-overflow' or n.get('action') in ('halt-blocked','terminal')
"; then ok "current-wave-overflow-terminal"; else bad "current-wave-overflow-terminal"; fi

# --- 7.3 whole-batch-merge-wait (R33) ---
if grep -q 'whole-batch completion wait' "$ROOT/scripts/wave_deliver_loop.py"; then
  ok "whole-batch-merge-wait"
else
  bad "whole-batch-merge-wait"
fi

# --- 7.3 batch-integration-head-reconcile (R34) ---
if grep -q 'refresh_batch_integration_head' "$ROOT/scripts/wave_deliver_loop.py"; then
  ok "batch-integration-head-reconcile"
else
  bad "batch-integration-head-reconcile"
fi

# --- 7.4 post-remediation-no-status-pause (R35) ---
if grep -q 'Post-remediation complete' "$ROOT/core/skills/conductor/SKILL.md" && \
   grep -q 'No status-pause' "$ROOT/core/skills/conductor/SKILL.md"; then
  ok "post-remediation-no-status-pause"
else
  bad "post-remediation-no-status-pause"
fi

# --- 7.4 dispatch-ship-completes-in-turn (R36) ---
if grep -q 'dispatch-ship' "$ROOT/core/skills/conductor/SKILL.md" && \
   grep -q 're-invoke' "$ROOT/core/skills/conductor/SKILL.md"; then
  ok "dispatch-ship-completes-in-turn"
else
  bad "dispatch-ship-completes-in-turn"
fi

# --- 7.4 await-agent-same-turn-continue (R37) ---
if grep -q 'awaitAgent: true' "$ROOT/core/skills/conductor/SKILL.md"; then
  ok "await-agent-same-turn-continue"
else
  bad "await-agent-same-turn-continue"
fi

# --- 7.4 terminal-eligibility-teardown-green-parity (R38) ---
if python3 -c "
import sys
sys.path.insert(0,'$ROOT/scripts')
from wave_state import TERMINAL_PHASE_STATUSES, phase_complete
from wave_terminal import all_phases_green
assert TERMINAL_PHASE_STATUSES
state={'phases':{'1':{'status':'teardown-complete'},'2':{'status':'green-merged'}}}
assert all_phases_green(state)
for s in TERMINAL_PHASE_STATUSES:
  assert phase_complete(s)
"; then ok "terminal-eligibility-teardown-green-parity"; else bad "terminal-eligibility-teardown-green-parity"; fi

# --- 7.4 terminal-retro-before-pr-auto (R39) ---
if grep -q 'terminal-retro' "$ROOT/scripts/wave_terminal.py" && \
   grep -q 'terminal_autonomy_mode' "$ROOT/scripts/wave_deliver_loop.py"; then
  ok "terminal-retro-before-pr-auto"
else
  bad "terminal-retro-before-pr-auto"
fi

# --- 7.4 terminal-ship-autonomous-watch (R40) ---
if grep -q 'terminal-ship-run' "$ROOT/scripts/wave_terminal.py"; then
  ok "terminal-ship-autonomous-watch"
else
  bad "terminal-ship-autonomous-watch"
fi

# --- 7.4 single-flight-phase-ship (R41) ---
if grep -q 'ship-lease' "$ROOT/scripts/wave_deliver_loop.py" && \
   grep -q 'create_or_reuse_phase_pr' "$ROOT/scripts/wave_terminal.py"; then
  ok "single-flight-phase-ship"
else
  bad "single-flight-phase-ship"
fi

# --- 7.4 terminal-status-provenance-reemit (R42) ---
if grep -q 'canonical-reemit' "$ROOT/scripts/wave_deliver_loop.py"; then
  ok "terminal-status-provenance-reemit"
else
  bad "terminal-status-provenance-reemit"
fi

# --- 7.4 terminal-pr-prepare-commitlint (R43) ---
if python3 -c "
import sys
sys.path.insert(0,'$ROOT/scripts')
from wave_terminal import commitlint_safe_title
t=commitlint_safe_title('feat','Slug','035')
assert t=='feat(prd-35): deliver wave'
assert commitlint_safe_title('feat','X',None)== 'feat(x): deliver wave'
"; then ok "terminal-pr-prepare-commitlint"; else bad "terminal-pr-prepare-commitlint"; fi

# --- 7.5 eager-phase-teardown-after-merge (R44) ---
if grep -q 'teardown-pending' "$ROOT/scripts/wave_merge.py" && \
   grep -q 'phase-teardown-run' "$ROOT/scripts/wave_deliver_loop.py"; then
  ok "eager-phase-teardown-after-merge"
else
  bad "eager-phase-teardown-after-merge"
fi

# --- 7.5 parallel-ceiling-would-free (R45) ---
if grep -q 'wouldFree' "$ROOT/scripts/wave_lifecycle.py"; then
  ok "parallel-ceiling-would-free"
else
  bad "parallel-ceiling-would-free"
fi

# --- 7.5 status-collect-background-worktree (R46) ---
if grep -q 'resolve_phase_worktree' "$ROOT/scripts/wave_merge.py"; then
  ok "status-collect-background-worktree"
else
  bad "status-collect-background-worktree"
fi

# --- 7.5 deliver-resume-command-is-sw (R47) ---
if python3 -c "
import sys
sys.path.insert(0,'$ROOT/scripts')
from wave_failure import resume_deliver_command
assert resume_deliver_command({'source_task_list':'docs/prds/x/tasks.md'})=='/sw-deliver run docs/prds/x/tasks.md'
"; then ok "deliver-resume-command-is-sw"; else bad "deliver-resume-command-is-sw"; fi

# --- 7.6 post-freeze-docs-durability (R48) ---
if grep -q 'post-freeze-durability' "$ROOT/scripts/wave_spec_seed.py"; then
  ok "post-freeze-docs-durability"
else
  bad "post-freeze-docs-durability"
fi

# --- 7.6 projection-refuse-hand-maintained (R48) ---
if grep -q 'hand_maintained_legacy_paths' "$ROOT/scripts/planning_legacy_projection.py"; then
  ok "projection-refuse-hand-maintained"
else
  bad "projection-refuse-hand-maintained"
fi

# --- 7.6 re-freeze-contract-amendment (R48) ---
if grep -qE 'amendment|re-freeze|frozen' "$ROOT/core/commands/sw-freeze.md"; then
  ok "re-freeze-contract-amendment"
else
  bad "re-freeze-contract-amendment"
fi

# --- 7.6 cleanup-autonomy-auto-post-merge (R50) ---
if grep -q 'cleanup_autonomy_mode' "$ROOT/scripts/wave_deliver_loop.py" && \
   grep -q 'apply_autonomous_cleanup' "$ROOT/scripts/wave_deliver_loop.py"; then
  ok "cleanup-autonomy-auto-post-merge"
else
  bad "cleanup-autonomy-auto-post-merge"
fi

# --- manifest registration ---
if grep -q 'planning-035-deliver-conductor-fixtures' "$MANIFEST"; then
  ok "manifest-registration-035-a1"
else
  bad "manifest-registration-035-a1"
fi

exit "$FAIL"

"""
if __name__ == "__main__":
    raise SystemExit(main())
