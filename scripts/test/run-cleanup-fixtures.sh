#!/usr/bin/env bash
# Fixtures for /sw-cleanup (PRD 007 Phase 10 — R28–R34, R56).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CLEANUP="$ROOT/scripts/cleanup.sh"
CLEANUP_PY="$ROOT/scripts/cleanup_lib.py"
FAIL=0

ok()   { echo "OK  $1"; }
bad()  { echo "FAIL $1"; FAIL=1; }

# --- cleanup-dry-run-default ---
FIX=$(mktemp -d)
trap 'rm -rf "$FIX"' EXIT
cd "$FIX"
git init -q
git config user.email test@test.com
git config user.name Test
git commit --allow-empty -q -m init
git branch -M main
git checkout -q -b feat/merged-demo
git commit --allow-empty -q -m feat
git checkout -q main
git merge --no-ff feat/merged-demo -q -m merge
if OUT=$(bash "$CLEANUP" 2>/dev/null) && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
r=d['report']
assert r['dryRun'] is True
assert any(i['kind']=='branch' and i['name']=='feat/merged-demo' for i in r['wouldRemove'])
assert any(i['reason']=='protected' for i in r['protected'] if i['kind']=='branch' and i['name']=='main')
"; then
  ok "cleanup-dry-run-default: dry-run lists merged branch + protects main"
else
  bad "cleanup-dry-run-default"
fi

# confirm gate without --yes refuses
set +e
bash "$CLEANUP" --confirm 2>/dev/null
EC=$?
set -e
if [[ "$EC" -eq 2 ]]; then
  ok "cleanup-dry-run-default: confirm requires --yes"
else
  bad "cleanup-dry-run-default: confirm gate ec=$EC"
fi

# --- cleanup-protects-inflight ---
mkdir -p .cursor
echo '{"verdict":"running","mergeJournal":{"phase":"alpha"}}' >.cursor/sw-deliver-state.json
echo '{"target":"feat/x"}' >.cursor/sw-deliver.lock
if bash "$CLEANUP" 2>/dev/null | python3 -c "
import json,sys
r=json.load(sys.stdin)['report']
assert any(i['kind']=='run-state' and i['reason']=='protected' for i in r['protected'])
"; then
  ok "cleanup-protects-inflight: in-flight deliver state protected"
else
  bad "cleanup-protects-inflight: in-flight state"
fi

if ! rg -q 'rm -rf' "$ROOT/scripts/cleanup_lib.py" && \
   ! rg -q '^\s*rm\s' "$ROOT/scripts/cleanup.sh"; then
  ok "cleanup-protects-inflight: no rm -rf invocation in cleanup scripts"
else
  bad "cleanup-protects-inflight: rm -rf invocation present"
fi

if rg -q 'worktree", "remove"' "$ROOT/scripts/cleanup_lib.py" && \
   rg -q 'worktree remove' "$ROOT/core/commands/sw-cleanup.md"; then
  ok "cleanup-protects-inflight: worktree remove documented"
else
  bad "cleanup-protects-inflight: worktree remove"
fi

# --- cleanup-squash-merge-aware ---
SQ=$(mktemp -d)
cd "$SQ"
git init -q
git config user.email test@test.com
git config user.name Test
git commit --allow-empty -q -m init
git branch -M main
git checkout -q -b feat/squash-only
echo squash-content >squash.txt && git add squash.txt && git commit -q -m only-on-branch
git checkout -q main
git merge --squash feat/squash-only -q
git commit -q -m 'squash feat'
if python3 "$CLEANUP_PY" "$SQ" 2>/dev/null | python3 -c "
import json,sys
r=json.load(sys.stdin)['report']
names=[i['name'] for i in r['wouldRemove'] if i['kind']=='branch']
assert 'feat/squash-only' in names
"; then
  ok "cleanup-squash-merge-aware: squash-merged branch detected"
else
  bad "cleanup-squash-merge-aware: squash merged"
fi
git checkout -q -b feat/indeterminate
echo unique >only.txt && git add only.txt && git commit -q -m unique
git checkout -q main
if python3 "$CLEANUP_PY" "$SQ" 2>/dev/null | python3 -c "
import json,sys
r=json.load(sys.stdin)['report']
prot=[i for i in r['protected'] if i['name']=='feat/indeterminate']
assert prot and prot[0]['reason'] in ('unmerged','indeterminate')
"; then
  ok "cleanup-squash-merge-aware: unmerged branch protected"
else
  bad "cleanup-squash-merge-aware: unmerged protected"
fi
rm -rf "$SQ"
cd "$FIX"

# --- cleanup-registered ---
CMD="$ROOT/core/commands/sw-cleanup.md"
if [[ -f "$CMD" ]] && rg -q '^description:.*dry-run' "$CMD" && \
   rg -q 'Does not' "$CMD" && rg -q 'sw-cleanup' "$CMD"; then
  ok "cleanup-registered: sw-cleanup command + description contract"
else
  bad "cleanup-registered"
fi
if [[ -x "$ROOT/scripts/cleanup.sh" ]]; then
  ok "cleanup-registered: cleanup.sh executable"
else
  bad "cleanup-registered: cleanup.sh executable"
fi

if [[ "$FAIL" -ne 0 ]]; then
  echo "cleanup fixtures: FAIL"
  exit 1
fi
echo "cleanup fixtures: PASS"
