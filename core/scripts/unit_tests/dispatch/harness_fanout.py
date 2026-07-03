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
# PRD 024 — program dependency gate (TR0/R35): fan-out refused until 023 green + R31 positive.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GATE_PY="$ROOT/scripts/fanout_gate.py"
PREREQ="$ROOT/scripts/test/pilot_022_prerequisite_check.py"
PILOT_FIX="$ROOT/scripts/unit_tests/w4/harness_pilot.py"
POSITIVE_PAIRS="$ROOT/scripts/test/fixtures/benefit-metric/positive-pairs.json"
INSUFFICIENT_PAIRS="$ROOT/scripts/test/fixtures/benefit-metric/insufficient-n-pairs.json"
FAIL=0

ok()  { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

copy_gate_deps() {
  local dest_root="$1"
  mkdir -p "$dest_root/scripts"
  for f in fanout_gate.py pilot_dependency_gate.py wave_plan_benefit.py kernel_classification.py; do
    cp "$ROOT/scripts/$f" "$dest_root/scripts/"
  done
}

# --- fanout-024-blocked-without-023-r31: prerequisites + R31 both required ---
if OUT=$(python3 "$GATE_PY" "$ROOT" status --pairs "$POSITIVE_PAIRS" 2>/dev/null || true) \
  && echo "$OUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d['verdict'] == 'pass', d
assert d['pilot']['verdict'] == 'pass', d
assert d['r31']['positive'] is True, d
"; then
  ok "fanout-024-blocked-without-023-r31"
else
  bad "fanout-024-blocked-without-023-r31"
fi

BLOCK_FIX=$(mktemp -d)
(
  cd "$BLOCK_FIX"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  git commit --allow-empty -q -m init
  git branch -M main
  mkdir -p scripts/test/fixtures/benefit-metric
  copy_gate_deps "$BLOCK_FIX"
  cp "$POSITIVE_PAIRS" scripts/test/fixtures/benefit-metric/positive-pairs.json
  set +e
  python3 scripts/fanout_gate.py "$BLOCK_FIX" enabled >/dev/null 2>&1
  EC=$?
  set -e
  [[ "$EC" -eq 20 ]]
) && ok "fanout-024-blocked-without-023-r31 pilot-prereq-refused" \
  || bad "fanout-024-blocked-without-023-r31 pilot-prereq-refused"
rm -rf "$BLOCK_FIX"

if OUT=$(python3 "$GATE_PY" "$ROOT" status --pairs "$INSUFFICIENT_PAIRS" --min-n 3 2>/dev/null || true) \
  && echo "$OUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d['verdict'] == 'fail', d
assert d['pilot']['verdict'] == 'pass', d
assert d['r31']['positive'] is False, d
assert 'r31-non-positive' in d['reasons'], d
"; then
  ok "fanout-024-blocked-without-023-r31 r31-non-positive-refused"
else
  bad "fanout-024-blocked-without-023-r31 r31-non-positive-refused"
fi

# --- fanout-024-insufficient-n-not-adopted: inconclusive N identical to negative (R35) ---
if OUT=$(python3 "$GATE_PY" "$ROOT" status --pairs "$INSUFFICIENT_PAIRS" --min-n 3 2>/dev/null || true) \
  && echo "$OUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d['verdict'] == 'fail', d
assert d['r31']['positive'] is False, d
assert d['r31']['failClosed'] is True, d
assert d['r31']['recommendation'] == 'canonical', d
"; then
  ok "fanout-024-insufficient-n-not-adopted status"
else
  bad "fanout-024-insufficient-n-not-adopted status"
fi

set +e
python3 "$GATE_PY" "$ROOT" enabled --pairs "$INSUFFICIENT_PAIRS" --min-n 3 >/dev/null 2>&1
EC_INSUF=$?
BLOCK_FIX2=$(mktemp -d)
copy_gate_deps "$BLOCK_FIX2"
python3 "$BLOCK_FIX2/scripts/fanout_gate.py" "$BLOCK_FIX2" enabled >/dev/null 2>&1
EC_PREREQ=$?
rm -rf "$BLOCK_FIX2"
set -e

if [[ "$EC_INSUF" -eq 20 && "$EC_PREREQ" -eq 20 && "$EC_INSUF" -eq "$EC_PREREQ" ]]; then
  ok "fanout-024-insufficient-n-not-adopted"
else
  bad "fanout-024-insufficient-n-not-adopted exit=$EC_INSUF prereq=$EC_PREREQ"
fi

# --- orchestrator-plan-rejects-unknown-step (R20): closed-world orchestrator tier ---
BAD_PROPOSAL=$(mktemp)
cat > "$BAD_PROPOSAL" <<'JSON'
{"steps": ["memory-prework", "triage", "not-a-real-step", "normalize"]}
JSON
if OUT=$(bash "$ROOT/scripts/wave.sh" plan validate --tier orchestrator --orchestrator-type debug --proposal "$BAD_PROPOSAL" 2>/dev/null || true)   && echo "$OUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d['verdict'] == 'reject', d
assert any('unknown/extraneous' in r for r in d.get('reasons', [])), d
"; then
  ok "orchestrator-plan-rejects-unknown-step"
else
  bad "orchestrator-plan-rejects-unknown-step"
fi
rm -f "$BAD_PROPOSAL"

GOOD_PROPOSAL=$(mktemp)
python3 -c "
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path('$ROOT') / 'scripts'))
from orchestrator_step_plan import canonical_orchestrator_chain
steps = canonical_orchestrator_chain(Path('$ROOT'), 'debug')
print(json.dumps({'steps': steps}))
" > "$GOOD_PROPOSAL"
if OUT=$(bash "$ROOT/scripts/wave.sh" plan validate --tier orchestrator --orchestrator-type debug --proposal "$GOOD_PROPOSAL" 2>/dev/null || true)   && echo "$OUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d['verdict'] == 'pass', d
assert d['plan']['tier'] == 'orchestrator', d
"; then
  ok "orchestrator-plan-accepts-canonical-debug"
else
  bad "orchestrator-plan-accepts-canonical-debug"
fi
rm -f "$GOOD_PROPOSAL"

# --- orchestrator-proposed-plan-rejects-deliver-only-steps (R18/SC4) ---
for ORCH in debug doc feedback; do
  BAD_DELIVER=$(mktemp)
  python3 -c "
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path('$ROOT') / 'scripts'))
from orchestrator_step_plan import canonical_orchestrator_chain
steps = canonical_orchestrator_chain(Path('$ROOT'), '$ORCH')
steps = list(steps)
steps.insert(1, 'merge-enqueue')
print(json.dumps({'steps': steps}))
" > "$BAD_DELIVER"
  if OUT=$(bash "$ROOT/scripts/wave.sh" plan validate --tier orchestrator --orchestrator-type "$ORCH" --proposal "$BAD_DELIVER" 2>/dev/null || true)     && echo "$OUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d['verdict'] == 'reject', d
assert any('forbidden deliver-only' in r for r in d.get('reasons', [])), d
"; then
    ok "orchestrator-proposed-plan-rejects-deliver-only-steps-$ORCH"
  else
    bad "orchestrator-proposed-plan-rejects-deliver-only-steps-$ORCH"
  fi
  rm -f "$BAD_DELIVER"
done

# --- orchestrator-consistency-only-defers-proposed-pack (R36) ---
if OUT=$(python3 "$ROOT/scripts/variance_probe.py" "$ROOT" probe doc 2>/dev/null || true)   && echo "$OUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d['verdict'] == 'pass', d
assert d['canonicalEquivProposed'] is True, d
assert d['adoptionMode'] == 'consistency-only', d
assert d['proposedPackDeferred'] is True, d
assert d['defaultsConsistencyOnly'] is True, d
"; then
  ok "orchestrator-consistency-only-defers-proposed-pack"
else
  bad "orchestrator-consistency-only-defers-proposed-pack"
fi

if OUT=$(python3 "$ROOT/scripts/variance_probe.py" "$ROOT" probe debug 2>/dev/null || true)   && echo "$OUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d['adoptionMode'] == 'full', d
assert d['proposedPackDeferred'] is False, d
"; then
  ok "orchestrator-consistency-only-defers-proposed-pack debug-full"
else
  bad "orchestrator-consistency-only-defers-proposed-pack debug-full"
fi

# --- consistency-only-exempts-proposed-fixtures (R36d) ---
DOC_EXEMPT_FIXTURES=(
  doc-proposed-routes-gate-selector
  doc-022-parity-under-proposed
  doc-review-halt-manual-required
  doc-review-halt-gated-auto-required
  doc-afterTasks-checkpoint-required
)
EXEMPT_OK=1
for FIX in "${DOC_EXEMPT_FIXTURES[@]}"; do
  if OUT=$(python3 "$ROOT/scripts/variance_probe.py" "$ROOT" proposed-fixture-exempt doc "$FIX" 2>/dev/null || true)     && echo "$OUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d['exempt'] is True, d
"; then
    :
  else
    EXEMPT_OK=0
    bad "consistency-only-exempts-proposed-fixtures $FIX"
  fi
done
if [[ "$EXEMPT_OK" -eq 1 ]]; then
  ok "consistency-only-exempts-proposed-fixtures"
fi

NON_EXEMPT_FIXTURE=debug-proposed-routes-gate-selector
if OUT=$(python3 "$ROOT/scripts/variance_probe.py" "$ROOT" proposed-fixture-exempt debug "$NON_EXEMPT_FIXTURE" 2>/dev/null || true)   && echo "$OUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d['exempt'] is False, d
"; then
  ok "consistency-only-exempts-proposed-fixtures debug-not-exempt"
else
  bad "consistency-only-exempts-proposed-fixtures debug-not-exempt"
fi

# --- doc-review-parallel-panel-binding (R38 + R39 integration) ---
PREFLIGHT_DIR="$ROOT/.cursor/hooks/state/task-dispatch-preflight"
WAVE="$ROOT/scripts/wave.sh"
rm -rf "$PREFLIGHT_DIR"
rm -f "$ROOT/.cursor/hooks/state/task-dispatch-preflight.json"
PANEL_AGENTS=(sw-coherence-reviewer sw-feasibility-reviewer sw-product-reviewer)
PANEL_IDS=(doc-panel-a doc-panel-b doc-panel-c)
PANEL_OK=1
for i in 0 1 2; do
  bash "$WAVE" dispatch preflight --dispatch-id "${PANEL_IDS[$i]}" --agent "${PANEL_AGENTS[$i]}" --command sw-doc-review --skill doc-review >/dev/null 2>&1 || PANEL_OK=0
done
if [[ "$PANEL_OK" -eq 1 ]]; then
  ALL_PASS=1
  for i in 0 1 2; do
    OUT=$(python3 - "$ROOT" "${PANEL_IDS[$i]}" "${PANEL_AGENTS[$i]}" <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / 'core' / 'hooks'))
from before_task_dispatch import evaluate_pre_tool_use
payload = {'tool_name': 'Task', 'tool_input': {'subagent_type': sys.argv[3], 'metadata': {'dispatchId': sys.argv[2]}}}
result = evaluate_pre_tool_use(payload, Path(sys.argv[1]))
print(json.dumps({'verdict': result.verdict, 'cause': result.cause}))
PY
)
    echo "$OUT" | python3 -c "import json,sys; assert json.load(sys.stdin)['verdict']=='pass'" || ALL_PASS=0
  done
  if [[ "$ALL_PASS" -eq 1 ]]; then
    ok "doc-review-parallel-panel-binding"
  else
    bad "doc-review-parallel-panel-binding (hook)"
  fi
else
  bad "doc-review-parallel-panel-binding (preflight)"
fi
rm -rf "$PREFLIGHT_DIR"
rm -f "$ROOT/.cursor/hooks/state/task-dispatch-preflight.json"



# --- cross-orchestrator-state-isolation (TR6/R37e) ---
if OUT=$(python3 "$ROOT/scripts/orchestrator_run.py" "$ROOT" isolation-check 2>/dev/null || true)   && echo "$OUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d['verdict'] == 'pass', d
assert d['debugDeliverStateWrite']['verdict'] == 'reject', d
assert d['debugSelectorWrite']['verdict'] == 'reject', d
"; then
  ok "cross-orchestrator-state-isolation"
else
  bad "cross-orchestrator-state-isolation"
fi

# --- non-deliver-episodic-no-durable-resume (R37a–R37d) ---
EPISODIC_OK=1
for ORCH in debug feedback; do
  if OUT=$(python3 "$ROOT/scripts/orchestrator_run.py" "$ROOT" episodic-check --orchestrator-type "$ORCH" 2>/dev/null || true)     && echo "$OUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d['verdict'] == 'pass', d
assert d['resume']['resumeRevalidatesPlanPolicyMode'] == 'N/A', d
"; then
    :
  else
    EPISODIC_OK=0
    bad "non-deliver-episodic-no-durable-resume-$ORCH"
  fi
done
if [[ "$EPISODIC_OK" -eq 1 ]]; then
  ok "non-deliver-episodic-no-durable-resume"
fi

# --- signal-context-capture-before-validate (TR3) ---
CAPTURE_INPUT='{"signal_type":"sentry","related_files":["src/a.ts"],"sentry_ref":"evt-1"}'
if OUT=$(python3 "$ROOT/scripts/orchestrator_signal_context.py" "$ROOT" capture --orchestrator-type debug --run-id capture-fixture --input "$CAPTURE_INPUT" 2>/dev/null || true)   && echo "$OUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d['verdict'] == 'pass', d
assert d['snapshotPoint'] == 'before-plan-validate', d
sc = d['signal_context']
assert sc['owner'] == 'session/ephemeral', sc
assert sc['signal_type'] == 'sentry', sc
"; then
  ok "signal-context-capture-before-validate"
  python3 "$ROOT/scripts/orchestrator_run.py" "$ROOT" teardown --orchestrator-type debug --run-id capture-fixture >/dev/null 2>&1 || true
else
  bad "signal-context-capture-before-validate"
fi


# --- Phase 6: /sw-doc adoption (consistency-only, TR4b, R18–R20, R36c) ---
if OUT=$(python3 "$ROOT/scripts/orchestrator_run.py" "$ROOT" canonical-parity-check --orchestrator-type doc 2>/dev/null || true)   && echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='pass', d"; then
  ok "doc-canonical-parity"
else
  bad "doc-canonical-parity"
fi

DOC_HALT_CASES=(
  "doc-review-halt-manual-required|doc-review-halt-manual|{\"doc_review_mode\":\"manual\"}"
  "doc-review-halt-gated-auto-required|doc-review-halt-gated-auto|{\"doc_review_mode\":\"gated_auto\"}"
  "doc-afterTasks-checkpoint-required|afterTasks-checkpoint|"
)
for CASE in "${DOC_HALT_CASES[@]}"; do
  IFS='|' read -r FIX_NAME HALT SIG <<<"$CASE"
  BAD=$(mktemp)
  python3 -c "
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path('$ROOT') / 'scripts'))
from orchestrator_step_plan import canonical_orchestrator_chain
steps = [s for s in canonical_orchestrator_chain(Path('$ROOT'), 'doc') if s != '$HALT']
print(json.dumps({'steps': steps}))
" > "$BAD"
  if [[ -n "$SIG" ]]; then
    if OUT=$(bash "$ROOT/scripts/wave.sh" plan validate --tier orchestrator --orchestrator-type doc --proposal "$BAD" --signal-context "$SIG" 2>/dev/null || true)       && echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='reject', d"; then
      ok "$FIX_NAME"
    else
      bad "$FIX_NAME"
    fi
  else
    if OUT=$(bash "$ROOT/scripts/wave.sh" plan validate --tier orchestrator --orchestrator-type doc --proposal "$BAD" 2>/dev/null || true)       && echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='reject', d"; then
      ok "$FIX_NAME"
    else
      bad "$FIX_NAME"
    fi
  fi
  rm -f "$BAD"
done

# --- Phase 5: /sw-debug adoption fixtures (TR4a, R18–R23) ---
if OUT=$(python3 "$ROOT/scripts/orchestrator_run.py" "$ROOT" canonical-parity-check 2>/dev/null || true)   && echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='pass', d"; then
  ok "debug-canonical-parity"
else
  bad "debug-canonical-parity"
fi

if OUT=$(python3 "$ROOT/scripts/orchestrator_run.py" "$ROOT" proposed-routes-check 2>/dev/null || true)   && echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='pass', d"; then
  ok "debug-proposed-routes-gate-selector"
else
  bad "debug-proposed-routes-gate-selector"
fi

for HALT in route-confirm-halt rca-human-decision-halt; do
  BAD=$(mktemp)
  python3 -c "
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path('$ROOT') / 'scripts'))
from orchestrator_step_plan import canonical_orchestrator_chain
steps = [s for s in canonical_orchestrator_chain(Path('$ROOT'), 'debug') if s != '$HALT']
print(json.dumps({'steps': steps}))
" > "$BAD"
  FIX_NAME=$(echo "$HALT" | sed 's/-halt$//')
  if OUT=$(bash "$ROOT/scripts/wave.sh" plan validate --tier orchestrator --orchestrator-type debug --proposal "$BAD" 2>/dev/null || true)     && echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='reject', d"; then
    ok "debug-${FIX_NAME}-halt-required"
  else
    bad "debug-${FIX_NAME}-halt-required"
  fi
  rm -f "$BAD"
done

SENTRY_LIKE=$'breadcrumb: user clicked\nghp_abcdefghijklmnopqrstuvwxyz1234567890ABCD\nemail: leak@corp.example.com'
SCRUBBED=$(echo "$SENTRY_LIKE" | bash "$ROOT/scripts/memory-redact.sh")
if [[ "$SCRUBBED" == *'[REDACTED:'* ]] && [[ "$SCRUBBED" != *'ghp_abc'* ]]; then
  ok "debug-proposed-sentry-enrich-redact-before-preflight"
else
  bad "debug-proposed-sentry-enrich-redact-before-preflight"
fi

if OUT=$(python3 "$ROOT/scripts/orchestrator_run.py" "$ROOT" budget-trip-check 2>/dev/null || true)   && echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['tripped'] is True, d"; then
  ok "debug-budget-trip"
else
  bad "debug-budget-trip"
fi

if OUT=$(python3 "$ROOT/scripts/orchestrator_run.py" "$ROOT" r21-surfacing-check 2>/dev/null || true)   && echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='pass', d"; then
  ok "debug-r21-surfacing"
else
  bad "debug-r21-surfacing"
fi

PARITY022_OK=1
if ! python3 - <<PY
import sys
from pathlib import Path
sys.path.insert(0, "$ROOT/scripts")
from wave_plan_validate import read_config_plan_policy
assert read_config_plan_policy(Path("$ROOT")) == "proposed"
from capability_trust import MEMORY_GATES
assert "memory-preflight" in MEMORY_GATES
from kernel_classification import load_classification
data = load_classification(Path("$ROOT"))
ids = {c.get("id") for c in data.get("kernelChokepoints") or []}
for required in ("memory-preflight-routing", "beforeSubmitPrompt-guardrails"):
    assert required in ids, required
PY
then
  PARITY022_OK=0
fi
if [[ "$PARITY022_OK" -eq 1 ]] \
  && OUT=$(python3 "$ROOT/scripts/wave_plan_validate.py" "$ROOT" validate --tier orchestrator --orchestrator-type debug --proposal '{"steps":["memory-prework","triage"]}' 2>/dev/null || true) \
  && echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict'] in ('reject','ambiguous'), d"; then
  ok "debug-022-parity-under-proposed"
else
  bad "debug-022-parity-under-proposed"
fi


# --- Phase 7: /sw-feedback adoption (TR4c, R18–R23) ---
if OUT=$(python3 "$ROOT/scripts/orchestrator_run.py" "$ROOT" canonical-parity-check --orchestrator-type feedback 2>/dev/null || true)   && echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='pass', d"; then
  ok "feedback-canonical-parity"
else
  bad "feedback-canonical-parity"
fi

if OUT=$(python3 "$ROOT/scripts/orchestrator_run.py" "$ROOT" proposed-routes-check --orchestrator-type feedback 2>/dev/null || true)   && echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='pass', d"; then
  ok "feedback-proposed-routes-gate-selector"
else
  bad "feedback-proposed-routes-gate-selector"
fi

BAD_HOOK=$(mktemp)
python3 -c "
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path('$ROOT') / 'scripts'))
from orchestrator_step_plan import canonical_orchestrator_chain
steps = [s for s in canonical_orchestrator_chain(Path('$ROOT'), 'feedback') if s != 'hook-trigger-halt']
print(json.dumps({'steps': steps}))
" > "$BAD_HOOK"
if OUT=$(bash "$ROOT/scripts/wave.sh" plan validate --tier orchestrator --orchestrator-type feedback --proposal "$BAD_HOOK" --signal-context '{"source_class":"production","invocation":"hook"}' 2>/dev/null || true)   && echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='reject', d"; then
  ok "feedback-hook-trigger-no-autodispatch-under-proposed"
else
  bad "feedback-hook-trigger-no-autodispatch-under-proposed"
fi
rm -f "$BAD_HOOK"

BAD_CONFIRM=$(mktemp)
python3 -c "
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path('$ROOT') / 'scripts'))
from orchestrator_step_plan import canonical_orchestrator_chain
steps = [s for s in canonical_orchestrator_chain(Path('$ROOT'), 'feedback') if s != 'human-confirm-halt']
print(json.dumps({'steps': steps}))
" > "$BAD_CONFIRM"
if OUT=$(bash "$ROOT/scripts/wave.sh" plan validate --tier orchestrator --orchestrator-type feedback --proposal "$BAD_CONFIRM" --signal-context '{"source_class":"review","invocation":"human"}' 2>/dev/null || true)   && echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='reject', d"; then
  ok "feedback-proposed-human-confirm-before-dispatch"
else
  bad "feedback-proposed-human-confirm-before-dispatch"
fi
rm -f "$BAD_CONFIRM"

FEEDBACK_LIKE=$'review note: token ghp_abcdefghijklmnopqrstuvwxyz1234567890ABCD\nemail: leak@corp.example.com'
SCRUBBED_FB=$(echo "$FEEDBACK_LIKE" | bash "$ROOT/scripts/memory-redact.sh")
if [[ "$SCRUBBED_FB" == *'[REDACTED:'* ]] && [[ "$SCRUBBED_FB" != *'ghp_abc'* ]]; then
  ok "feedback-proposed-inbound-redact-fail-closed"
else
  bad "feedback-proposed-inbound-redact-fail-closed"
fi

if OUT=$(python3 "$ROOT/scripts/orchestrator_run.py" "$ROOT" budget-trip-check --orchestrator-type feedback 2>/dev/null || true)   && echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['tripped'] is True, d"; then
  ok "feedback-budget-trip"
else
  bad "feedback-budget-trip"
fi

if OUT=$(python3 "$ROOT/scripts/orchestrator_run.py" "$ROOT" r21-surfacing-check --orchestrator-type feedback 2>/dev/null || true)   && echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='pass', d"; then
  ok "feedback-r21-surfacing"
else
  bad "feedback-r21-surfacing"
fi

FB_PARITY022_OK=1
if ! python3 - <<'PY022'
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1] + "/scripts")
from wave_plan_validate import read_config_plan_policy
assert read_config_plan_policy(Path(sys.argv[1])) == "proposed"
from capability_trust import MEMORY_GATES
assert "memory-preflight" in MEMORY_GATES
from kernel_classification import load_classification
data = load_classification(Path(sys.argv[1]))
ids = {c.get("id") for c in data.get("kernelChokepoints") or []}
for required in ("memory-preflight-routing", "beforeSubmitPrompt-guardrails"):
    assert required in ids, required
PY022
"$ROOT"; then
  FB_PARITY022_OK=0
fi
if [[ "$FB_PARITY022_OK" -eq 1 ]] \
  && OUT=$(python3 "$ROOT/scripts/wave_plan_validate.py" "$ROOT" validate --tier orchestrator --orchestrator-type feedback --proposal '{"steps":["memory-prework","normalize"]}' 2>/dev/null || true) \
  && echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict'] in ('reject','ambiguous'), d"; then
  ok "feedback-022-parity-under-proposed"
else
  bad "feedback-022-parity-under-proposed"
fi


exit "$FAIL"

"""
if __name__ == "__main__":
    raise SystemExit(main())
