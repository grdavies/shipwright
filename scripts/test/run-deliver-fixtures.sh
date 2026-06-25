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

# --- phase-mode /sw-ship contract (R48/R18) ---
SW_SHIP="$(cd "$ROOT" && bash -c 'source scripts/test/fixture-lib.sh 2>/dev/null; content_path commands/sw-ship.md' 2>/dev/null || echo "$ROOT/core/commands/sw-ship.md")"
DELIVER_SKILL="$ROOT/core/skills/deliver/SKILL.md"
SHIP_STATUS="$ROOT/scripts/ship-phase-status.sh"

if grep -q '\-\-phase-mode' "$SW_SHIP" && grep -q 'SW_PHASE_MODE' "$SW_SHIP" && \
   grep -q 'merge-ready-green' "$SW_SHIP" && grep -q 'ship-phase-status.sh' "$SW_SHIP"; then
  echo "OK  deliver-phase-noninteractive: sw-ship phase-mode contract"
else
  echo "FAIL deliver-phase-noninteractive: sw-ship phase-mode contract"
  FAIL=1
fi

if grep -q 'Sub-agent dispatch spike' "$DELIVER_SKILL" && \
   grep -q 'inline two-stage review' "$DELIVER_SKILL" && \
   grep -q 'sw-subagent-dispatch' "$DELIVER_SKILL"; then
  echo "OK  deliver-phase-noninteractive: nested dispatch spike + inline fallback"
else
  echo "FAIL deliver-phase-noninteractive: deliver skill R63 docs"
  FAIL=1
fi

PDIR=$(mktemp -d)
trap 'rm -rf "$PDIR" "$DRYDIR" 2>/dev/null' EXIT
if OUT=$("$SHIP_STATUS" --verdict merge-ready-green --phase test-phase --out "$PDIR/status.json" 2>/dev/null) && \
   echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['verdict']=='merge-ready-green' and d['phaseMode'] is True and d['phase']=='test-phase'
"; then
  echo "OK  deliver-phase-noninteractive: merge-ready-green status"
else
  echo "FAIL deliver-phase-noninteractive: merge-ready-green status"
  FAIL=1
fi

if OUT=$("$SHIP_STATUS" --verdict blocked --cause "verification-gate:not-verified" --phase test-phase --out "$PDIR/blocked.json" 2>/dev/null) && \
   echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['verdict']=='blocked' and 'not-verified' in d['cause']
"; then
  echo "OK  deliver-phase-noninteractive: blocked status with cause"
else
  echo "FAIL deliver-phase-noninteractive: blocked status"
  FAIL=1
fi

set +e
"$SHIP_STATUS" --verdict blocked --phase x --out "$PDIR/x.json" 2>/dev/null
EC_BLK=$?
set -e
if [[ "$EC_BLK" -eq 2 ]]; then
  echo "OK  deliver-phase-noninteractive: blocked requires cause"
else
  echo "FAIL deliver-phase-noninteractive: blocked should require cause (ec=$EC_BLK)"
  FAIL=1
fi

# --- state, lock, journal, progress log (R28/R51/R54) ---
STATE_FIX=$(mktemp -d)
(
  cd "$STATE_FIX"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  mkdir -p .cursor docs/prds/004-wave-phase-orchestrator
  cp "$TASK_FROZEN" docs/prds/004-wave-phase-orchestrator/
  "$WAVE" plan --task-list docs/prds/004-wave-phase-orchestrator/tasks-004-wave-phase-orchestrator.md >/dev/null
  "$WAVE" state init --plan .cursor/sw-deliver-plan.json >/dev/null
  "$WAVE" lock acquire --target feat/wave-phase-orchestrator --nonblock >/dev/null
  set +e
  "$WAVE" lock acquire --target feat/wave-phase-orchestrator --nonblock 2>/dev/null
  LOCK_DUP=$?
  set -e
  if [[ "$LOCK_DUP" -eq 20 ]]; then
    echo "OK  deliver-phase-interrupt-lock: second lock refuses"
  else
    echo "FAIL deliver-phase-interrupt-lock: expected exit 20 got $LOCK_DUP"
    FAIL=1
  fi
  "$WAVE" state phase --id 1 --status in-flight >/dev/null
  "$WAVE" journal begin --phase rename-deliver >/dev/null
  "$WAVE" journal complete --phase rename-deliver >/dev/null
  if "$WAVE" state get 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
s=d['state']
assert s['phases']['1']['status']=='in-flight'
assert s['mergeJournal'] is None
"; then
    echo "OK  deliver-phase-resume: run-state schema + phase transition"
  else
    echo "FAIL deliver-phase-resume: run-state schema"
    FAIL=1
  fi
  if "$WAVE" log tail --lines 5 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
events=[e['event'] for e in d['entries']]
assert 'phase-transition' in events and 'lock-acquire' in events
"; then
    echo "OK  deliver-phase-resume: append-only run log"
  else
    echo "FAIL deliver-phase-resume: run log"
    FAIL=1
  fi
  "$WAVE" lock release >/dev/null
) || { echo "FAIL deliver-phase-state-lock fixtures"; FAIL=1; }

SW_COMMIT="$(cd "$ROOT" && bash -c 'source scripts/test/fixture-lib.sh; content_path commands/sw-commit.md' 2>/dev/null || echo "$ROOT/core/commands/sw-commit.md")"
if grep -q 'sw-deliver-state.json' "$SW_COMMIT" && grep -q 'sw-deliver-runs' "$SW_COMMIT"; then
  echo "OK  deliver-phase-commit-exclude: sw-commit excludes deliver artifacts"
else
  echo "FAIL deliver-phase-commit-exclude"
  FAIL=1
fi

# --- contention preflight (R11/R12) ---
CONTEND="$FIX/tasks-contention.md"
cat >"$CONTEND" <<'EOF'
---
frozen: true
topic: contention-test
---
### 1. Alpha
- **File:** `scripts/shared-config.ts`
### 2. Beta
- **File:** `scripts/shared-config.ts`
### 3. Gamma
- **File:** `scripts/other.ts`
## Phase Dependencies
| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | none |
| 3 | none |
EOF
if OUT=$("$WAVE" plan --task-list "$CONTEND" --dry-run 2>/dev/null) && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert any('contention:' in n for n in d.get('notices',[]))
injected=[(e['from'],e['to']) for e in d['contention'].get('injectedEdges',[])]
assert ('1','2') in injected
assert '2' not in d['waves'][0]
assert d['waves']==[['1','3'],['2']]
"; then
  echo "OK  deliver-phase-contention-serialize"
else
  echo "FAIL deliver-phase-contention-serialize"
  FAIL=1
fi

CONTEND_SERIAL="$FIX/tasks-contention-serial.md"
cat >"$CONTEND_SERIAL" <<'EOF'
---
frozen: true
topic: contention-serial
---
### 1. One
- **File:** `shared/x.ts`
### 2. Two
- **File:** `shared/y.ts`
## Phase Dependencies
| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
EOF
if OUT=$("$WAVE" plan --task-list "$CONTEND_SERIAL" --dry-run 2>/dev/null) && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['contention'].get('injectedEdges',[])==[]
assert d['waves']==[['1'],['2']]
"; then
  echo "OK  deliver-phase-contention-skip-serial"
else
  echo "FAIL deliver-phase-contention-skip-serial"
  FAIL=1
fi

if python3 <<PY
import importlib.util
from pathlib import Path
spec = importlib.util.spec_from_file_location(
    "wave_deliver", Path("$ROOT/scripts/wave_deliver.py")
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
assert mod.graph_has_cycle(
    ["1", "2"],
    [{"from": "1", "to": "2"}, {"from": "2", "to": "1"}],
)
PY
then
  echo "OK  deliver-phase-contention-cycle-detect"
else
  echo "FAIL deliver-phase-contention-cycle-detect"
  FAIL=1
fi

# --- greedy scheduler ceiling (R14/R44) ---
SCHED_FIX=$(mktemp -d)
mkdir -p "$SCHED_FIX/.cursor"
echo '{"waves":[["1"],["2","3","4"]]}' >"$SCHED_FIX/.cursor/sw-deliver-plan.json"
if OUT=$("$WAVE" schedule --plan "$SCHED_FIX/.cursor/sw-deliver-plan.json" --ceiling 2 2>/dev/null) && \
   echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['parallelCeiling']==2
wave2=[w for w in d['schedule'] if w['wave']==2][0]
assert len(wave2['batches'])==2
assert wave2['batches'][0]['parallel']==['2','3']
assert wave2['batches'][1]['parallel']==['4']
assert wave2['countsTowardCeiling'] is True
"; then
  echo "OK  deliver-phase-schedule-ceiling"
else
  echo "FAIL deliver-phase-schedule-ceiling"
  echo "$OUT"
  FAIL=1
fi
rm -rf "$SCHED_FIX"

DELIVER_SKILL="$ROOT/core/skills/deliver/SKILL.md"
PAR_SKILL="$ROOT/core/skills/parallelism/SKILL.md"
if grep -q 'wave.sh schedule' "$DELIVER_SKILL" && grep -q 'parallelCeiling' "$DELIVER_SKILL"; then
  echo "OK  deliver-phase-schedule-docs"
else
  echo "FAIL deliver-phase-schedule-docs"
  FAIL=1
fi

PAR_SKILL="$ROOT/core/skills/parallelism/SKILL.md"
if grep -q 'injectedEdges' "$PAR_SKILL" || grep -q 'contention:' "$PAR_SKILL"; then
  echo "OK  deliver-phase-contention-docs"
else
  echo "FAIL deliver-phase-contention-docs"
  FAIL=1
fi

# --- orchestrator worktree + lifecycle (R16/R20/R21/R40/R53) ---
LIFE_FIX=$(mktemp -d)
LCY="$ROOT/scripts/wave_lifecycle.py"
(
  cd "$LIFE_FIX"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  echo base >README.md
  git add README.md
  git commit -q -m init
  git branch -m main
  git checkout -q -b feat/demo
  echo feature >>README.md
  git add README.md
  git commit -q -m feat
  mkdir -p .cursor
  echo '{"mode":"phase","target":{"branch":"feat/demo","slug":"demo"},"items":[{"id":"1","slug":"alpha","title":"A","branch":"feat/demo-phase-alpha"}]}' \
    >.cursor/sw-deliver-plan.json
  if OUT=$(python3 "$LCY" "$LIFE_FIX" orchestrator provision --target feat/demo 2>/dev/null) && \
     echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['countsTowardCeiling'] is False
assert 'orchestrator' in d['path']
"; then
    echo "OK  deliver-phase-orchestrator-worktree"
  else
    echo "FAIL deliver-phase-orchestrator-worktree"
    exit 1
  fi
  if python3 "$LCY" "$LIFE_FIX" orchestrator status 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['provisioned'] is True
"; then
    echo "OK  deliver-phase-orchestrator-status"
  else
    echo "FAIL deliver-phase-orchestrator-status"
    exit 1
  fi
) || FAIL=1

MERGE_FIX=$(mktemp -d)
(
  cd "$MERGE_FIX"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  echo line1 >shared.txt
  git add shared.txt && git commit -q -m init
  git branch -m main
  git checkout -q -b feat/demo
  echo demo >>shared.txt && git add shared.txt && git commit -q -m demo
  git worktree add -q -b feat/demo-phase-alpha "$MERGE_FIX/phase-wt" feat/demo
  echo phase >>"$MERGE_FIX/phase-wt/shared.txt"
  git -C "$MERGE_FIX/phase-wt" add shared.txt
  git -C "$MERGE_FIX/phase-wt" commit -q -m phase
  printf 'line1\ndemo\nconflict\n' >shared.txt && git add shared.txt && git commit -q -m advance-base
  set +e
  python3 "$LCY" "$MERGE_FIX" forward-merge --worktree "$MERGE_FIX/phase-wt" --base feat/demo 2>/dev/null
  EC=$?
  set -e
  if [[ "$EC" -eq 20 ]]; then
    echo "OK  deliver-phase-forward-merge-blocked"
  else
    echo "FAIL deliver-phase-forward-merge-blocked ec=$EC"
    exit 1
  fi
  git -C "$MERGE_FIX/phase-wt" reset -q --hard feat/demo
  echo phase2 >>"$MERGE_FIX/phase-wt/shared.txt"
  git -C "$MERGE_FIX/phase-wt" commit -q -am phase2
  if OUT=$(python3 "$LCY" "$MERGE_FIX" forward-merge --worktree "$MERGE_FIX/phase-wt" --base feat/demo 2>/dev/null) && \
     echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='pass'"; then
    echo "OK  deliver-phase-forward-merge-pass"
  else
    echo "FAIL deliver-phase-forward-merge-pass"
    exit 1
  fi
  git worktree add -q -b feat/demo-phase-beta "$MERGE_FIX/beta-wt" feat/demo
  if OUT=$(python3 "$LCY" "$MERGE_FIX" phase-teardown --worktree "$MERGE_FIX/beta-wt" 2>/dev/null) && \
     [[ ! -d "$MERGE_FIX/beta-wt" ]]; then
    echo "OK  deliver-phase-teardown"
  else
    echo "FAIL deliver-phase-teardown"
    exit 1
  fi
) || FAIL=1
rm -rf "$LIFE_FIX" "$MERGE_FIX"

SW_DELIVER="$ROOT/core/commands/sw-deliver.md"
if grep -q 'assert-entry' "$SW_DELIVER" && grep -q 'orchestrator provision' "$SW_DELIVER"; then
  echo "OK  deliver-phase-assert-entry"
else
  echo "FAIL deliver-phase-assert-entry"
  FAIL=1
fi

if grep -q 'countsTowardCeiling' "$ROOT/core/skills/deliver/SKILL.md" && \
   grep -q 'forward-merge' "$ROOT/core/skills/deliver/SKILL.md"; then
  echo "OK  deliver-phase-lifecycle-docs"
else
  echo "FAIL deliver-phase-lifecycle-docs"
  FAIL=1
fi

# --- merge queue + status collection (R13/R17/R38/R52/R55) ---
WM="$ROOT/scripts/wave_merge.py"
if OUT=$("$WAVE" phase dispatch-env --phase-slug alpha 2>/dev/null) && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['exports']['SW_PHASE_MODE']=='1'
assert d['invoke']=='/sw-ship --phase-mode'
"; then
  echo "OK  deliver-phase-dispatch-env"
else
  echo "FAIL deliver-phase-dispatch-env"
  FAIL=1
fi

STATUS_FIX=$(mktemp -d)
mkdir -p "$STATUS_FIX/.cursor/sw-deliver-runs/alpha"
cat >"$STATUS_FIX/.cursor/sw-deliver-runs/alpha/status.json" <<'JSON'
{"verdict":"merge-ready-green","phase":"alpha","phaseMode":true,"head":"abc123","pr":99}
JSON
if OUT=$(python3 "$WM" "$STATUS_FIX" status collect --phase-slug alpha 2>/dev/null) && \
   echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['status']['verdict']=='merge-ready-green'"; then
  echo "OK  deliver-phase-status-collect"
else
  echo "FAIL deliver-phase-status-collect"
  FAIL=1
fi

if python3 <<PY
import importlib.util
from pathlib import Path
spec = importlib.util.spec_from_file_location("wm", Path("$WM"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
assert mod.merge_authorizing(0, {"verdict": "green", "coderabbitLanded": True})
assert not mod.merge_authorizing(10, {"verdict": "yellow", "coderabbitLanded": False})
assert not mod.merge_authorizing(0, {"verdict": "green", "coderabbitLanded": False})
PY
then
  echo "OK  deliver-phase-merge-gate-barrier"
else
  echo "FAIL deliver-phase-merge-gate-barrier"
  FAIL=1
fi

cat >"$STATUS_FIX/.cursor/sw-deliver-state.json" <<'JSON'
{"target":{"branch":"feat/demo"},"phases":{"1":{"id":"1","slug":"alpha","branch":"feat/demo-phase-alpha","status":"pending"}},"mergeQueue":[]}
JSON
if OUT=$(python3 "$WM" "$STATUS_FIX" merge enqueue --phase-slug alpha 2>/dev/null) && \
   echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['queueLength']==1"; then
  echo "OK  deliver-phase-merge-enqueue"
else
  echo "FAIL deliver-phase-merge-enqueue"
  FAIL=1
fi

MERGE_Q_FIX=$(mktemp -d)
(
  cd "$MERGE_Q_FIX"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  echo base >f.txt && git add f.txt && git commit -q -m init
  git branch -m feat/demo
  git checkout -q -b feat/demo-phase-alpha
  echo phase >>f.txt && git add f.txt && git commit -q -m phase
  git checkout -q feat/demo
  mkdir -p .cursor
  echo '{"target":{"branch":"feat/demo"},"orchestratorWorktree":{"path":"'"$MERGE_Q_FIX"'"}}' >.cursor/sw-deliver-state.json
  if OUT=$(python3 "$WM" "$MERGE_Q_FIX" merge exec --phase-slug alpha --phase-branch feat/demo-phase-alpha --target feat/demo 2>/dev/null) && \
     echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['method']=='merge'"; then
    echo "OK  deliver-phase-merge-exec"
  else
    echo "FAIL deliver-phase-merge-exec"
    exit 1
  fi
  if python3 "$WM" "$MERGE_Q_FIX" merge ancestry-check --phase-branch feat/demo-phase-alpha --target feat/demo 2>/dev/null \
    | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['merged'] is True"; then
    echo "OK  deliver-phase-ancestry-check"
  else
    echo "FAIL deliver-phase-ancestry-check"
    exit 1
  fi
) || FAIL=1
rm -rf "$STATUS_FIX" "$MERGE_Q_FIX"

cat >"$ROOT/.cursor/sw-deliver-state-test-terminal.json" <<'JSON'
{"target":{"branch":"feat/demo"},"phases":{"1":{"slug":"alpha","status":"green-merged"}},"mergedPhases":[{"phaseSlug":"alpha","pr":42,"mergeCommit":"deadbeef"}]}
JSON
# use temp copy
TERM_FIX=$(mktemp -d)
mkdir -p "$TERM_FIX/.cursor"
cp "$ROOT/.cursor/sw-deliver-state-test-terminal.json" "$TERM_FIX/.cursor/sw-deliver-state.json" 2>/dev/null || \
  echo '{"target":{"branch":"feat/demo"},"phases":{"1":{"slug":"alpha","status":"green-merged"}},"mergedPhases":[{"phaseSlug":"alpha","pr":42,"mergeCommit":"deadbeef"}]}' >"$TERM_FIX/.cursor/sw-deliver-state.json"
if OUT=$(python3 "$WM" "$TERM_FIX" report terminal 2>/dev/null) && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
r=d['report']
assert r['verdict']=='complete'
assert r['terminalGate']=='ready to merge — your call'
assert r['phasePrs'][0]['pr']==42
"; then
  echo "OK  deliver-phase-report-terminal"
else
  echo "FAIL deliver-phase-report-terminal"
  FAIL=1
fi
rm -rf "$TERM_FIX" "$ROOT/.cursor/sw-deliver-state-test-terminal.json" 2>/dev/null

DELIVER_SKILL="$ROOT/core/skills/deliver/SKILL.md"
if grep -q 'merge run-next' "$DELIVER_SKILL" && grep -q 'status collect' "$DELIVER_SKILL" && \
   grep -q 'report terminal' "$DELIVER_SKILL"; then
  echo "OK  deliver-phase-merge-queue-docs"
else
  echo "FAIL deliver-phase-merge-queue-docs"
  FAIL=1
fi

exit "$FAIL"
