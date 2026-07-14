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
# PRD 017 Testing Strategy — pervasive sub-agent delegation fixture aggregate (R19–R21).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FAIL=0
SCENARIOS=()

ok()   { echo "OK  $1"; SCENARIOS+=("$1"); }
bad()  { echo "FAIL $1"; FAIL=1; }

DISPATCH_RULE="$ROOT/core/rules/sw-subagent-dispatch.mdc"
CONDUCTOR_SKILL="$ROOT/core/skills/conductor/SKILL.md"
CONDUCTOR_RULE="$ROOT/core/rules/sw-conductor.mdc"
ROUTING_DEFAULTS="$ROOT/core/sw-reference/communication-routing.defaults.json"
TIERING="$ROOT/.sw/models-tiering.md"
LAYOUT="$ROOT/.sw/layout.md"
WORKFLOWS="$ROOT/docs/guides/workflows.md"
CONFIG="$ROOT/.cursor/workflow.config.json"
SCHEMA="$ROOT/.sw/config.schema.json"
DISPATCH_CHECK="$ROOT/scripts/dispatch-check.sh"
INTENSITY="$ROOT/scripts/resolve-intensity.sh"
MODEL_RESOLVE="$ROOT/scripts/resolve-model-tier.sh"
LOOP_PY="$ROOT/scripts/wave_deliver_loop.py"
LCY_PY="$ROOT/scripts/wave_lifecycle.py"
WAVE="$ROOT/scripts/wave.sh"

ORCHESTRATORS=(sw-ship sw-debug sw-doc sw-feedback sw-deliver)

# --- delegation-default-invariant (R1, R2) ---
INV_FAIL=0
for cmd in "${ORCHESTRATORS[@]}"; do
  f="$ROOT/core/commands/${cmd}.md"
  if ! grep -qE 'Inline allowlist|inline allowlist' "$f" 2>/dev/null; then
    INV_FAIL=1
    break
  fi
  if ! grep -qE 'dispatch preflight|Delegated Task binding|Delegated atomics' "$f" 2>/dev/null; then
    INV_FAIL=1
    break
  fi
done
if [[ "$INV_FAIL" -eq 0 ]] && grep -q 'delegate-by-default' "$DISPATCH_RULE"; then
  ok "delegation-default-invariant"
else
  bad "delegation-default-invariant"
fi

# --- dispatch-rule-default-gate (R3) ---
if grep -q 'delegate-by-default' "$DISPATCH_RULE" && \
   grep -q 'delegation.mode' "$DISPATCH_RULE" && \
   ! grep -qE 'standing gate.*8\+|8\+ files.*standing gate' "$DISPATCH_RULE"; then
  ok "dispatch-rule-default-gate"
else
  bad "dispatch-rule-default-gate"
fi

# --- delegation-mode-knob (R22a) ---
if python3 - <<'PY' "$SCHEMA" "$ROOT/core/sw-reference/config.schema.json"
import json, sys
for path in sys.argv[1:]:
    schema = json.load(open(path))
    mode = schema["properties"]["delegation"]["properties"]["mode"]
    assert set(mode["enum"]) == {"bind-only", "heuristic", "default"}
    assert mode["default"] in {"bind-only", "default"}
PY
then
  ok "delegation-mode-knob"
else
  bad "delegation-mode-knob"
fi

# --- dispatch-binds-model (R4) ---
if OUT=$(bash "$MODEL_RESOLVE" --agent sw-coherence-reviewer --config "$CONFIG" 2>/dev/null) && \
   echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('modelId') and d['modelId']!='inherit'"; then
  BIND_FAIL=0
  for cmd in "${ORCHESTRATORS[@]}"; do
    if ! grep -qE 'explicit.*model:|model: <resolved|never.*inherit' "$ROOT/core/commands/${cmd}.md" 2>/dev/null; then
      BIND_FAIL=1
      break
    fi
  done
  if [[ "$BIND_FAIL" -eq 0 ]]; then
    ok "dispatch-binds-model"
  else
    bad "dispatch-binds-model"
  fi
else
  bad "dispatch-binds-model"
fi

# --- dispatch-binds-intensity (R5) ---
if OUT=$(bash "$INTENSITY" --command sw-doc-review --config "$CONFIG" 2>/dev/null) && \
   echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('intensity') in {'normal','lite','full','ultra'}"; then
  ok "dispatch-binds-intensity"
else
  bad "dispatch-binds-intensity"
fi

# --- intensity-routing-extended (R6, R7) ---
if python3 - <<'PY' "$SCHEMA" "$ROUTING_DEFAULTS"
import json, sys
schema = json.load(open(sys.argv[1]))
defaults = json.load(open(sys.argv[2]))
routing = (
    schema.get("properties", {})
    .get("communication", {})
    .get("properties", {})
    .get("routing", {})
    .get("properties", {})
)
assert "skills" in routing and "agents" in routing
dr = defaults.get("routing", {})
assert dr.get("skills") and dr.get("agents")
PY
then
  if OUT=$(bash "$INTENSITY" --skill doc-review --config "$CONFIG" 2>/dev/null) && \
     echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('source','').startswith('routing.')"; then
    ok "intensity-routing-extended"
  else
    bad "intensity-routing-extended"
  fi
else
  bad "intensity-routing-extended"
fi

# --- dispatch-hook-forward-compat (R8) ---
if bash "$ROOT/scripts/test/fixtures/task-dispatch-hook-feasibility.sh" >/dev/null 2>&1; then
  ok "dispatch-hook-forward-compat"
else
  bad "dispatch-hook-forward-compat"
fi

# --- dispatch-check-fail-closed (R9) ---
BROKEN="$ROOT/.cursor/delegation-broken-$$.json"
python3 - <<'PY' "$CONFIG" "$BROKEN"
import json, sys
cfg = json.load(open(sys.argv[1]))
cfg = dict(cfg)
models = dict(cfg.get("models", {}))
models["tiers"] = {}
cfg["models"] = models
json.dump(cfg, open(sys.argv[2], "w"))
PY
set +e
OUT=$(bash "$DISPATCH_CHECK" --agent sw-coherence-reviewer --command sw-doc-review --parent-model composer-2.5 --config "$BROKEN" 2>/dev/null)
EC=$?
set -e
rm -f "$BROKEN"
if [[ "$EC" -eq 20 ]] && echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('cause','').startswith('binding:')"; then
  ok "dispatch-check-fail-closed"
else
  bad "dispatch-check-fail-closed"
fi

# --- dispatch-check-cause-enum (R10) ---
set +e
OUT=$(bash "$DISPATCH_CHECK" --agent sw-coherence-reviewer --command sw-doc-review --parent-model composer-2.5 --simulate-capacity 2>/dev/null)
EC=$?
set -e
if [[ "$EC" -eq 20 ]] && echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('cause')=='harness:capacity' and d.get('retryable')"; then
  ok "dispatch-check-cause-enum"
else
  bad "dispatch-check-cause-enum"
fi

# --- dispatch-preflight-nonce-gate (R23) ---
if bash "$WAVE" dispatch preflight --dispatch-id fixture-delegation-preflight --agent sw-coherence-reviewer --command sw-doc-review --skill doc-review >/dev/null 2>&1; then
  HOOK_OUT=$(python3 - <<'PY' "$ROOT"
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "core" / "hooks"))
from before_task_dispatch import evaluate_pre_tool_use
payload = {"tool_name": "Task", "tool_input": {"subagent_type": "sw-coherence-reviewer", "prompt": "**Resolved intensity:** `normal` (dispatch-preflight)\nfixture task"}}
result = evaluate_pre_tool_use(payload, Path(sys.argv[1]))
print(json.dumps({"verdict": result.verdict, "model": result.model_id}))
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

# --- intensity-precedence-no-double-resolve (R24) ---
SESSION_CTX="$ROOT/core/hooks/session-context.md"
if grep -q 'dispatch-preflight binding overrides session-start' "$SESSION_CTX" && \
   grep -q 'resolve-intensity.py' "$TIERING"; then
  ok "intensity-precedence-no-double-resolve"
else
  bad "intensity-precedence-no-double-resolve"
fi

# --- dispatch-override-audited (R26) ---
OVERRIDE_ID="fixture-delegation-override-$$"
set +e
OUT=$(bash "$DISPATCH_CHECK" --agent sw-coherence-reviewer --command sw-doc-review --parent-model composer-2.5-fast --override --dispatch-id "$OVERRIDE_ID" --config "$CONFIG" 2>/dev/null)
EC=$?
set -e
if [[ "$EC" -eq 20 ]] && echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('cause')=='binding:no-override-audit'"; then
  ok "dispatch-override-audited"
else
  bad "dispatch-override-audited"
fi

# --- dispatch-prompt-redacted (R25) ---
RED_FAIL=0
for cmd in "${ORCHESTRATORS[@]}"; do
  if ! grep -q 'memory-redact.sh' "$ROOT/core/commands/${cmd}.md" 2>/dev/null; then
    RED_FAIL=1
    break
  fi
done
if [[ "$RED_FAIL" -eq 0 ]]; then
  ok "dispatch-prompt-redacted"
else
  bad "dispatch-prompt-redacted"
fi

# --- parallel-batch-driver (R22) ---
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
  "target": {"branch": "feat/batch"},
  "items": [
    {"id": "1", "slug": "a", "branch": "feat/batch-phase-a"},
    {"id": "2", "slug": "b", "branch": "feat/batch-phase-b"}
  ],
  "edges": [],
  "waves": [["1", "2"]]
}
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
    "2": {"id": "2", "slug": "b", "status": "pending"}
  },
  "phaseWorktrees": {
    "1": {"path": "/tmp/a", "name": "a"},
    "2": {"path": "/tmp/b", "name": "b"}
  }
}
JSON
  if OUT=$(python3 "$LOOP_PY" "$BATCH_FIX" compute-next 2>/dev/null) && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
n=d['next']
assert n['action']=='dispatch-batch'
assert len(n.get('phaseIds',[]))>=2
"; then
    exit 0
  fi
  exit 1
) && ok "parallel-batch-driver" || bad "parallel-batch-driver"
rm -rf "$BATCH_FIX"

# --- parallel-peak-concurrency-runtime (R11) ---
if python3 - <<'PY' "$LOOP_PY"
import json, subprocess, sys, tempfile, os, shutil
from pathlib import Path
from datetime import datetime, timezone

fix = tempfile.mkdtemp()
try:
    os.chdir(fix)
    subprocess.run(["git", "init", "-q"], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], check=True, capture_output=True)
    subprocess.run(["git", "commit", "--allow-empty", "-q", "-m", "init"], check=True, capture_output=True)
    Path(".cursor").mkdir()
    Path(".cursor/sw-base-state.json").write_text('{"trunkBase":{"name":"main","sha":"abc"}}')
    Path(".cursor/sw-deliver-plan.json").write_text(json.dumps({
        "mode": "phase",
        "target": {"branch": "feat/x"},
        "items": [{"id": str(i), "slug": c} for i, c in enumerate(["a", "b", "c"], 1)],
        "waves": [["1", "2", "3"]],
        "edges": [],
    }))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    Path(".cursor/sw-deliver-state.json").write_text(json.dumps({
        "verdict": "running",
        "target": {"branch": "feat/x"},
        "currentWave": 1,
        "specSeed": {"skipped": True},
        "baseCapture": {"skipped": True},
        "orchestratorWorktree": {"path": "/tmp/o"},
        "driverHeartbeatAt": now,
        "phases": {
            str(i): {"id": str(i), "slug": c, "status": "pending"}
            for i, c in enumerate(["a", "b", "c"], 1)
        },
        "phaseWorktrees": {
            str(i): {"path": f"/tmp/{c}", "name": c}
            for i, c in enumerate(["a", "b", "c"], 1)
        },
    }))
    out = subprocess.check_output([sys.executable, sys.argv[1], fix, "compute-next"], text=True)
    n = json.loads(out)["next"]
    assert n["action"] == "dispatch-batch"
    assert len(n.get("phaseIds", [])) >= 2
    assert "background" in n.get("note", "").lower()
finally:
    shutil.rmtree(fix, ignore_errors=True)
PY
then
  ok "parallel-peak-concurrency-runtime"
else
  bad "parallel-peak-concurrency-runtime"
fi

# --- parallel-collect-all-ready (R27) ---
# Clear ambient SW_DRIVER_STALE_SECONDS overrides (e.g. agent shell after timeout-halt
# fixtures elsewhere). PRD 065 merge-ready seeding can exceed a 60s override.
unset SW_DRIVER_STALE_SECONDS
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
    "1": {"id": "1", "slug": "a", "status": "in-flight", "branch": "feat/collect-phase-a"},
    "2": {"id": "2", "slug": "b", "status": "in-flight", "branch": "feat/collect-phase-b"}
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
  for slug in a b; do
    run=".cursor/sw-deliver-runs/$slug"
    mkdir -p "$run"
    PYTHONPATH="$ROOT/scripts" python3 -c "
import json, sys
from pathlib import Path
from kernel_classification import canonical_ship_chain
repo = Path(sys.argv[1]); slug = sys.argv[2]; run = Path(sys.argv[3])
chain = canonical_ship_chain(repo)
(run / 'ship-steps.json').write_text(json.dumps({'phase': slug, 'chain': chain, 'lastCompletedStep': chain[-1], 'currentStep': None}))
" "$ROOT" "$slug" "$run" >/dev/null
    SW_RUN_DIR="$run" SW_PHASE_SLUG="$slug" \
      "$ROOT/scripts/ship-phase-status.sh" --verdict merge-ready-green --phase "$slug" --head "$HEAD" \
      --out "$run/status.json" >/dev/null
  done
  if OUT=$(python3 "$LOOP_PY" "$COLLECT_FIX" compute-next 2>/dev/null) && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['next']['action']=='collect-all-ready'
assert [p['phaseSlug'] for p in d['next']['phases']]==['a','b']
"; then
    exit 0
  fi
  exit 1
) && ok "parallel-collect-all-ready" || bad "parallel-collect-all-ready"
rm -rf "$COLLECT_FIX"

# --- parallel-background-task-failure (R27) ---
BG_FIX=$(mktemp -d)
(
  cd "$BG_FIX"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  git commit --allow-empty -q -m init
  mkdir -p .cursor
  cat >.cursor/sw-base-state.json <<'JSON'
{"trunkBase": {"name": "main", "sha": "deadbeef00000000000000000000000000000000"}}
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
    exit 0
  fi
  exit 1
) && ok "parallel-background-task-failure" || bad "parallel-background-task-failure"
rm -rf "$BG_FIX"

# --- ceiling-slot-accounting (R12) ---
if OUT=$(python3 "$LCY_PY" "$ROOT" orchestrator provision --target feat/ceiling-fixture --dry-run 2>/dev/null || true) && \
   grep -q 'countsTowardCeiling' "$ROOT/scripts/wave_lifecycle.py" && \
   grep -q 'countsTowardCeiling' "$ROOT/core/skills/deliver/SKILL.md"; then
  ok "ceiling-slot-accounting"
else
  if grep -q 'countsTowardCeiling' "$ROOT/scripts/wave_lifecycle.py" && \
     python3 - <<'PY' "$LCY_PY" "$ROOT"
import json, subprocess, sys
out = subprocess.check_output([sys.executable, sys.argv[1], sys.argv[2], "phase", "dispatch-env", "--phase-slug", "alpha"], text=True)
d = json.loads(out)
assert d.get("countsTowardCeiling") is True or "parallelCeiling" in json.dumps(d)
PY
  then
    ok "ceiling-slot-accounting"
  else
    bad "ceiling-slot-accounting"
  fi
fi

# --- conductor-only-merge-lock (R13) ---
if grep -qE 'Phase sub-agents must not|must not call.*merge' "$CONDUCTOR_RULE" && \
   grep -qE 'lock acquire' "$CONDUCTOR_RULE"; then
  ok "conductor-only-merge-lock"
else
  bad "conductor-only-merge-lock"
fi

# --- phase-push-chokepoint (R13) ---
if grep -q 'git-push.py' "$CONDUCTOR_SKILL" && \
   grep -q 'git-push.py' "$CONDUCTOR_RULE" && \
   grep -qE 'Never raw.*git push|no raw.*git push' "$CONDUCTOR_RULE"; then
  ok "phase-push-chokepoint"
else
  bad "phase-push-chokepoint"
fi

# --- conductor-no-status-pause (R14) ---
if grep -q 'No status-pause' "$CONDUCTOR_SKILL" && \
   grep -q 'No status-pause' "$CONDUCTOR_RULE" && \
   ! grep -qE 'Want me to continue' "$CONDUCTOR_SKILL"; then
  ok "conductor-no-status-pause"
else
  bad "conductor-no-status-pause"
fi

# --- conductor-post-remediation-complete (R15) ---
if grep -q 'Post-remediation complete' "$CONDUCTOR_SKILL" && \
   grep -q 'merge-ready-green' "$CONDUCTOR_SKILL"; then
  ok "conductor-post-remediation-complete"
else
  bad "conductor-post-remediation-complete"
fi

# --- conductor-reinvoke-after-dispatch-ship (R16) ---
if grep -q 'Silent dispatch window' "$CONDUCTOR_SKILL" && \
   grep -q 're-invoke' "$CONDUCTOR_SKILL"; then
  ok "conductor-reinvoke-after-dispatch-ship"
else
  bad "conductor-reinvoke-after-dispatch-ship"
fi

# --- conductor-driver-detected-halt-only (R28) ---
if grep -q 'Driver-detected halts only' "$CONDUCTOR_SKILL" && \
   grep -q 'report blockers' "$CONDUCTOR_SKILL"; then
  ok "conductor-driver-detected-halt-only"
else
  bad "conductor-driver-detected-halt-only"
fi

# --- phase-teardown-eager-safe (R17) ---
if grep -q 'teardown-pending' "$ROOT/scripts/wave_state.py" && \
   grep -q 'teardown-complete' "$ROOT/scripts/wave_merge.py" && \
   grep -qE 'phase-teardown|teardown-pending' "$ROOT/scripts/wave_lifecycle.py"; then
  ok "phase-teardown-eager-safe"
else
  bad "phase-teardown-eager-safe"
fi

# --- conductor-single-source (R18) ---
CS_FAIL=0
for cmd in "${ORCHESTRATORS[@]}"; do
  if ! grep -q 'skills/conductor/SKILL.md' "$ROOT/core/commands/${cmd}.md" 2>/dev/null; then
    CS_FAIL=1
    break
  fi
done
if [[ "$CS_FAIL" -eq 0 ]]; then
  ok "conductor-single-source"
else
  bad "conductor-single-source"
fi

# --- orchestrator-delegation-per-command (R18, TR8) ---
OD_FAIL=0
for cmd in sw-ship sw-debug sw-doc sw-feedback; do
  f="$ROOT/core/commands/${cmd}.md"
  if ! grep -q 'dispatch-check.py' "$f" || ! grep -q 'resolve-intensity.py' "$f"; then
    OD_FAIL=1
    break
  fi
done
if [[ "$OD_FAIL" -eq 0 ]] && grep -q 'dispatch preflight' "$ROOT/core/commands/sw-deliver.md"; then
  ok "orchestrator-delegation-per-command"
else
  bad "orchestrator-delegation-per-command"
fi

# --- deliver-resume-command-is-sw (R29) ---
if python3 - <<'PY' "$ROOT"
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "scripts"))
from wave_failure import resume_deliver_command
cmd = resume_deliver_command({"source_task_list": "docs/prds/017-x/tasks.md"})
assert cmd.startswith("/sw-deliver run "), cmd
assert "bash" not in cmd
PY
then
  ok "deliver-resume-command-is-sw"
else
  bad "deliver-resume-command-is-sw"
fi

# --- deliver-resume-docs-sw-form (R29) ---
DELIVER_CMD="$ROOT/core/commands/sw-deliver.md"
DELIVER_SKILL="$ROOT/core/skills/deliver/SKILL.md"
if grep -qE '/sw-deliver run' "$DELIVER_CMD" && \
   grep -qE '/sw-deliver run' "$CONDUCTOR_SKILL" && \
   grep -qE '/sw-deliver run|resumeCommand' "$DELIVER_SKILL" && \
   grep -q 'resumeCommand' "$CONDUCTOR_SKILL"; then
  ok "deliver-resume-docs-sw-form"
else
  bad "deliver-resume-docs-sw-form"
fi

# --- delegation-emitter-freshness (R19) ---
if python3 "$ROOT/scripts/unit_tests/meta/harness_emitter.py" >/dev/null 2>&1; then
  ok "delegation-emitter-freshness"
else
  bad "delegation-emitter-freshness"
fi

# --- delegation-docs-presence (R21) ---
if grep -q 'delegate-by-default' "$DISPATCH_RULE" && \
   grep -q 'dispatch-check.py' "$DISPATCH_RULE" && \
   grep -q 'resolve-intensity.py' "$TIERING" && \
   grep -q '"skills"' "$ROUTING_DEFAULTS" && \
   grep -q 'delegation' "$WORKFLOWS" && \
   grep -q 'dispatch preflight' "$LAYOUT"; then
  ok "delegation-docs-presence"
else
  bad "delegation-docs-presence"
fi

# Traceability summary
REQUIRED=(
  delegation-default-invariant
  dispatch-rule-default-gate
  delegation-mode-knob
  dispatch-binds-model
  dispatch-binds-intensity
  intensity-routing-extended
  dispatch-hook-forward-compat
  dispatch-check-fail-closed
  dispatch-check-cause-enum
  dispatch-preflight-nonce-gate
  intensity-precedence-no-double-resolve
  dispatch-override-audited
  dispatch-prompt-redacted
  parallel-batch-driver
  parallel-peak-concurrency-runtime
  parallel-collect-all-ready
  parallel-background-task-failure
  ceiling-slot-accounting
  conductor-only-merge-lock
  phase-push-chokepoint
  conductor-no-status-pause
  conductor-post-remediation-complete
  conductor-reinvoke-after-dispatch-ship
  conductor-driver-detected-halt-only
  phase-teardown-eager-safe
  conductor-single-source
  orchestrator-delegation-per-command
  deliver-resume-command-is-sw
  deliver-resume-docs-sw-form
  delegation-emitter-freshness
  delegation-docs-presence
)
MISSING=()
for name in "${REQUIRED[@]}"; do
  found=0
  for s in "${SCENARIOS[@]}"; do
    [[ "$s" == "$name" ]] && found=1 && break
  done
  [[ "$found" -eq 0 ]] && MISSING+=("$name")
done
if [[ "${#MISSING[@]}" -gt 0 ]]; then
  echo "TRACEABILITY GAP: ${MISSING[*]}"
  FAIL=1
fi

echo "delegation-fixtures: ${#SCENARIOS[@]}/${#REQUIRED[@]} scenarios"
if [[ "$FAIL" -ne 0 ]]; then
  echo "run-delegation-fixtures: FAIL"
  exit 1
fi
echo "run-delegation-fixtures: PASS"
exit 0

"""
if __name__ == "__main__":
    raise SystemExit(main())
