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


exit "$FAIL"
