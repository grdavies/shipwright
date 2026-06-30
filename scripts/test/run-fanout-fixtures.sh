#!/usr/bin/env bash
# PRD 024 — program dependency gate (TR0/R35): fan-out refused until 023 green + R31 positive.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GATE_PY="$ROOT/scripts/fanout_gate.py"
PREREQ="$ROOT/scripts/test/pilot-022-prerequisite-check.sh"
PILOT_FIX="$ROOT/scripts/test/run-pilot-fixtures.sh"
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
if bash "$PREREQ" >/dev/null 2>&1 \
  && bash "$PILOT_FIX" >/dev/null 2>&1 \
  && OUT=$(python3 "$GATE_PY" "$ROOT" status --pairs "$POSITIVE_PAIRS" 2>/dev/null || true) \
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


exit "$FAIL"
