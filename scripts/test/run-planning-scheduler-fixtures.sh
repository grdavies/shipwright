#!/usr/bin/env bash
# Planning scheduler + deliver dependency gate fixtures (PRD 033 phase 3).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="$ROOT/scripts:$ROOT/core/scripts"
GATE="$ROOT/scripts/planning_deliver_gate.py"
WD="$ROOT/scripts/wave_deliver.py"
FIX="$ROOT/scripts/test/fixtures/planning-scheduler"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

setup_repo() {
  local dest="$1"
  rm -rf "$dest"
  mkdir -p "$dest"
  cp -R "$FIX/corpus/." "$dest/"
  (
    cd "$dest"
    git init -q
    git config user.email test@test.com
    git config user.name Test
    git add -A
    git commit -q -m init
  )
}

# --- dependency-gate-fail-closed (R7) ---
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
setup_repo "$TMP/gate"
if OUT=$(python3 "$GATE" "$TMP/gate" dependency-gate preflight --task-list docs/prds/prd-scheduler-blocked/tasks-prd-scheduler-blocked.md 2>&1) && false; then
  bad "dependency-gate-fail-closed"
elif echo "$OUT" | python3 -c "import json,sys; d=json.loads(sys.stdin.read().split('\n')[-1] if '{' in sys.stdin.read() else sys.stdin.read()); assert d.get('halt')=='dependency-gate'; assert 'prd-scheduler-missing' in d.get('blockingUnits',[])" 2>/dev/null; then
  ok "dependency-gate-fail-closed"
else
  # parse last json object line
  if python3 -c "
import subprocess, json, sys
p=subprocess.run(['python3','$GATE','$TMP/gate','dependency-gate','preflight','--task-list','docs/prds/prd-scheduler-blocked/tasks-prd-scheduler-blocked.md'],capture_output=True,text=True)
d=json.loads(p.stdout or '{}') if p.stdout.strip().startswith('{') else {}
if p.returncode==20 and d.get('halt')=='dependency-gate' and 'prd-scheduler-missing' in (d.get('blockingUnits') or []):
    sys.exit(0)
sys.exit(1)
"; then ok "dependency-gate-fail-closed"; else bad "dependency-gate-fail-closed"; fi
fi

# --- soft-enforce-confirm-stubbed-default (R8) ---
setup_repo "$TMP/soft"
EC=0
OUT=$(python3 "$WD" "$TMP/soft" dependency-gate preflight --task-list docs/prds/prd-scheduler-low/tasks-prd-scheduler-low.md 2>&1) || EC=$?
if [[ "$EC" -eq 30 ]] && echo "$OUT" | grep -q '"verdict": "confirm"'; then
  ok "soft-enforce-confirm-stubbed-default"
else
  bad "soft-enforce-confirm-stubbed-default"
fi

# --- run-start-revalidate-supersede-refuse (R9) ---
setup_repo "$TMP/super"
EC=0
OUT=$(python3 "$GATE" "$TMP/super" dependency-gate run-start --task-list docs/prds/prd-scheduler-super/tasks-prd-scheduler-super.md 2>&1) || EC=$?
if [[ "$EC" -eq 20 ]] && echo "$OUT" | grep -q 'run-start-ineligible'; then
  ok "run-start-revalidate-supersede-refuse"
else
  bad "run-start-revalidate-supersede-refuse"
fi

# --- deliver-dependency-preflight (R20) ---
setup_repo "$TMP/pref"
if OUT=$(python3 "$WD" "$TMP/pref" dependency-gate preflight --task-list docs/prds/prd-scheduler-high/tasks-prd-scheduler-high.md 2>&1) && echo "$OUT" | grep -q 'dependency-gate-preflight'; then
  ok "deliver-dependency-preflight"
else
  bad "deliver-dependency-preflight"
fi

# --- override-logged-rate-surfaced (R28) ---
setup_repo "$TMP/ovr"
( cd "$TMP/ovr" && bash "$ROOT/scripts/shipwright-state.sh" init '{}' >/dev/null )
python3 "$GATE" "$TMP/ovr" dependency-gate preflight --task-list docs/prds/prd-scheduler-blocked/tasks-prd-scheduler-blocked.md --override --override-reason "pilot waiver" >/dev/null || true
if python3 -c "
import json
from pathlib import Path
p=Path('$TMP/ovr/.git/shipwright.json')
assert p.is_file()
data=json.loads(p.read_text())
ovs=[o for o in data.get('overrides',[]) if o.get('kind')=='dependency-gate']
assert len(ovs)>=1 and ovs[-1].get('why')=='pilot waiver'
"; then
  ok "override-logged-rate-surfaced"
else
  bad "override-logged-rate-surfaced"
fi

# --- next selects highest priority ---
setup_repo "$TMP/next"
if OUT=$(python3 "$GATE" "$TMP/next" next 2>&1) && echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('unitId')=='prd-scheduler-high'"; then
  ok "next-selects-priority"
else
  bad "next-selects-priority"
fi

exit "$FAIL"
