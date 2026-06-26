#!/usr/bin/env bash
# Fixtures for orchestrator branch ownership + spec-seed (PRD 007 Phase 4 — R6/R40/R55/R57).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LIFE="$ROOT/scripts/wave_lifecycle.py"
SEED="$ROOT/scripts/wave_spec_seed.py"
FAIL=0

ok()   { echo "OK  $1"; }
bad()  { echo "FAIL $1"; FAIL=1; }

# --- orchestrator-owns-branch ---
FIX=$(mktemp -d)
trap 'rm -rf "$FIX"' EXIT
cd "$FIX"
git init -q
git config user.email test@test.com
git config user.name Test
git commit --allow-empty -q -m init
git branch -M main
git checkout -q -b feat/demo

set +e
python3 "$LIFE" "$FIX" orchestrator provision --target feat/demo 2>/dev/null
EC_PRIMARY=$?
set -e
if [[ "$EC_PRIMARY" -eq 0 ]] && [[ "$(git branch --show-current)" == "main" ]]; then
  ok "orchestrator-owns-branch: auto-moves primary off target before provision"
else
  bad "orchestrator-owns-branch: expected exit 0 with primary on main got ec=$EC_PRIMARY branch=$(git branch --show-current)"
fi

WT_PATH="$FIX/.sw-worktrees/demo-orchestrator"
if [[ -d "$WT_PATH" ]]; then
  git worktree remove --force "$WT_PATH" 2>/dev/null || rm -rf "$WT_PATH"
  git worktree prune
fi

git checkout -q feat/demo
echo dirty >dirty.txt
set +e
python3 "$LIFE" "$FIX" orchestrator provision --target feat/demo 2>/dev/null
EC_DIRTY=$?
set -e
rm -f dirty.txt
if [[ "$EC_DIRTY" -eq 20 ]]; then
  ok "orchestrator-owns-branch: dirty primary on target fails closed"
else
  bad "orchestrator-owns-branch: dirty primary expected exit 20 got $EC_DIRTY"
fi

git checkout -q main
set +e
OUT=$(python3 "$LIFE" "$FIX" orchestrator provision --target feat/demo 2>/dev/null)
EC_OK=$?
set -e
if [[ "$EC_OK" -eq 0 ]] && echo "$OUT" | python3 -c "
import json,sys,subprocess
d=json.load(sys.stdin)
path=d['path']
wt=subprocess.check_output(['git','-C',path,'symbolic-ref','-q','HEAD'], text=True).strip()
assert wt.endswith('feat/demo')
"; then
  ok "orchestrator-owns-branch: non-detached orchestrator checkout"
else
  bad "orchestrator-owns-branch: non-detached provision ec=$EC_OK"
fi

# --- deliver-spec-seed-feature-branch + spec-seed-single-owner-idempotent ---
SEED_FIX=$(mktemp -d)
(
  cd "$SEED_FIX"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  git commit --allow-empty -q -m init
  git branch -M main
  mkdir -p docs/prds/099-demo
  cat >docs/prds/099-demo/tasks-099-demo.md <<'EOF'
---
frozen: true
topic: demo
prd: docs/prds/099-demo/099-prd-demo.md
---
### 1. Demo phase only
EOF
  git add docs/prds/099-demo/
  git commit -q -m 'add frozen tasks on main'

  if OUT=$(python3 "$SEED" "$SEED_FIX" spec-seed --task-list docs/prds/099-demo/tasks-099-demo.md 2>/dev/null) && \
     echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['branch']=='feat/demo'
assert d.get('commit') or d.get('skipped')
" && [[ "$(git branch --show-current)" == "main" ]]; then
    echo "OK  deliver-spec-seed-feature-branch: seeds onto feat/demo; primary returns to main"
  else
    echo "FAIL deliver-spec-seed-feature-branch"
    exit 1
  fi

  if python3 "$SEED" "$SEED_FIX" spec-seed --task-list docs/prds/099-demo/tasks-099-demo.md 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('skipped') is True
"; then
    echo "OK  spec-seed-single-owner-idempotent: second run is no-op"
  else
    echo "FAIL spec-seed-single-owner-idempotent"
    exit 1
  fi
) || FAIL=1
rm -rf "$SEED_FIX"

if rg -q 'wave\.sh spec-seed' "$ROOT/core/commands/sw-doc.md" && \
   rg -q 'spec-seed' "$ROOT/scripts/wave_deliver_loop.py"; then
  ok "spec-seed-single-owner-idempotent: sw-doc + deliver-loop share helper"
else
  bad "spec-seed-single-owner-idempotent: shared helper wiring"
fi

if [[ "$FAIL" -ne 0 ]]; then
  echo "orchestrator fixtures: FAIL"
  exit 1
fi
echo "orchestrator fixtures: PASS"
