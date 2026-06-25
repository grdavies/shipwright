#!/usr/bin/env bash
# Fixtures for /sw-deliver phase-mode planning (PRD 004 phase 2+).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WAVE="$ROOT/scripts/wave.sh"
FIX="$ROOT/scripts/test/fixtures/deliver-phase"
TASK_FROZEN="$ROOT/docs/prds/004-wave-phase-orchestrator/tasks-004-wave-phase-orchestrator.md"
FAIL=0

run_json() {
  local name="$1" expect_ec="$2"
  shift 2
  set +e
  OUT=$("$@" 2>/dev/null)
  EC=$?
  set -e
  if [[ "$EC" -eq "$expect_ec" ]]; then
    echo "OK  $name exit=$EC"
  else
    echo "FAIL $name expected exit=$expect_ec got exit=$EC"
    echo "$OUT"
    FAIL=1
  fi
}

# --- mode detect: task-list → phase-mode ---
run_json deliver-mode-detect-phase 0 "$WAVE" preflight \
  --task-list docs/prds/004-wave-phase-orchestrator/tasks-004-wave-phase-orchestrator.md
if "$WAVE" preflight --task-list docs/prds/004-wave-phase-orchestrator/tasks-004-wave-phase-orchestrator.md 2>/dev/null \
  | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['mode']=='phase' and d['target']['branch']=='feat/wave-phase-orchestrator'"; then
  echo "OK  deliver-mode-detect: phase target branch"
else
  echo "FAIL deliver-mode-detect: phase target branch"
  FAIL=1
fi

# --- mode detect: items → multi-feature ---
run_json deliver-mode-detect-multi 0 "$WAVE" preflight --items 'A,B' --edges 'B:A'
if "$WAVE" preflight --items 'A,B' --edges 'B:A' 2>/dev/null \
  | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['mode']=='multi-feature'"; then
  echo "OK  deliver-mode-detect: multi-feature mode"
else
  echo "FAIL deliver-mode-detect: multi-feature mode"
  FAIL=1
fi

# --- disambiguation halt ---
run_json deliver-mode-detect-ambiguous 2 "$WAVE" preflight \
  --task-list docs/prds/004-wave-phase-orchestrator/tasks-004-wave-phase-orchestrator.md \
  --items 'A,B'

# --- explicit phase DAG from task list ---
if OUT=$("$WAVE" plan --task-list docs/prds/004-wave-phase-orchestrator/tasks-004-wave-phase-orchestrator.md --dry-run 2>/dev/null) && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['mode']=='phase'
assert d['source_task_list']
assert d['prd_number']=='004'
assert len(d['items'])>=13
assert d['waves']
assert all('slug' in i for i in d['items'])
"; then
  echo "OK  deliver-phase-plan-explicit"
else
  echo "FAIL deliver-phase-plan-explicit"
  FAIL=1
fi

# --- cycle refuse ---
CYCLIC="$FIX/tasks-cycle.md"
cat >"$CYCLIC" <<'EOF'
---
frozen: true
topic: cycle-test
---
### 1. One
### 2. Two
## Phase Dependencies
| Phase | Depends on |
|-------|------------|
| 1 | 2 |
| 2 | 1 |
EOF
run_json deliver-phase-cycle 20 "$WAVE" plan --task-list "$CYCLIC"

# --- sequential fallback ---
SEQ="$FIX/tasks-sequential.md"
cat >"$SEQ" <<'EOF'
---
frozen: true
topic: seq-test
---
### 1. First
### 2. Second
### 3. Third
EOF
if OUT=$("$WAVE" plan --task-list "$SEQ" 2>/dev/null) && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert any('sequential fallback' in n for n in d.get('notices',[]))
edges=[(e['from'],e['to']) for e in d['edges']]
assert ('1','2') in edges and ('2','3') in edges
"; then
  echo "OK  deliver-phase-sequential-fallback"
else
  echo "FAIL deliver-phase-sequential-fallback"
  FAIL=1
fi

# --- frozen guard ---
UNFROZEN="$FIX/tasks-unfrozen.md"
cat >"$UNFROZEN" <<'EOF'
---
frozen: false
topic: unfrozen-test
---
### 1. Only
EOF
run_json deliver-phase-frozen-guard 2 "$WAVE" plan --task-list "$UNFROZEN"

# --- branch type ---
if "$WAVE" plan --task-list "$TASK_FROZEN" --type docs --dry-run 2>/dev/null \
  | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['target']['type']=='docs' and d['target']['branch']=='docs/wave-phase-orchestrator'"; then
  echo "OK  deliver-phase-branch-type"
else
  echo "FAIL deliver-phase-branch-type"
  FAIL=1
fi

# --- dry-run writes no plan file ---
DRYDIR=$(mktemp -d)
trap 'rm -rf "$DRYDIR"' EXIT
(
  cd "$DRYDIR"
  git init -q && git commit --allow-empty -m init -q
  mkdir -p docs/prds/004-wave-phase-orchestrator
  cp "$TASK_FROZEN" docs/prds/004-wave-phase-orchestrator/
  "$WAVE" plan --task-list docs/prds/004-wave-phase-orchestrator/tasks-004-wave-phase-orchestrator.md --dry-run >/dev/null
  test ! -f .cursor/sw-deliver-plan.json
) && echo "OK  deliver-phase-dry-run" || { echo "FAIL deliver-phase-dry-run"; FAIL=1; }

# --- multi-feature baseline unchanged ---
run_json deliver-multi-feature-baseline 0 "$WAVE" plan --items 'A,B,C' --edges 'C:A'

exit "$FAIL"
