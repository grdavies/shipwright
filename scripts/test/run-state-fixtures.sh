#!/usr/bin/env bash
# Fixtures for crash-safe durable state (PRD 007 Phase 2 — R43/R44/R45).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STATE_PY="$ROOT/scripts/wave_state.py"
FAIL=0

ok()   { echo "OK  $1"; }
bad()  { echo "FAIL $1"; FAIL=1; }

STATE_FIX=$(mktemp -d)
trap 'rm -rf "$STATE_FIX"' EXIT

cd "$STATE_FIX"
git init -q
git config user.email test@test.com
git config user.name Test
git commit --allow-empty -q -m init
mkdir -p .cursor

# --- state-write-atomic-crash: corrupt file halts, not silent empty ---
echo '{not-json' > .cursor/sw-deliver-state.json
set +e
OUT=$(python3 "$STATE_PY" "$STATE_FIX" state get 2>&1)
EC=$?
set -e
if [[ "$EC" -eq 20 ]] && echo "$OUT" | grep -qE 'corrupt|state:corrupt'; then
  ok "state-write-atomic-crash: corrupt state halts (exit 20)"
else
  bad "state-write-atomic-crash: expected corrupt halt ec=20 got ec=$EC"
fi

# --- atomic write round-trip ---
python3 -c "
from pathlib import Path
import sys
sys.path.insert(0, '$ROOT/scripts')
from wave_json_io import read_json, write_json
p = Path('.cursor/sw-deliver-state.json')
write_json(p, {'verdict': 'running', 'phases': {}})
assert read_json(p)['verdict'] == 'running'
" && ok "state-write-atomic-crash: atomic write/read round-trip" || bad "state-write-atomic-crash: atomic write/read round-trip"

# --- lock-stale-reclaim: dead pid + stale heartbeat lock is reclaimed ---
echo '{"target":"feat/x","pid":999999999,"host":"test","acquiredAt":"2020-01-01T00:00:00Z","heartbeatAt":"2020-01-01T00:00:00Z"}' \
  > .cursor/sw-deliver.lock
if python3 "$STATE_PY" "$STATE_FIX" lock acquire --target feat/x --nonblock >/dev/null 2>&1; then
  ok "lock-stale-reclaim: stale/dead-owner lock reclaimed"
else
  bad "lock-stale-reclaim: stale/dead-owner lock reclaimed"
fi
python3 "$STATE_PY" "$STATE_FIX" lock release --target feat/x >/dev/null 2>&1 || true

# --- fresh heartbeat: second acquire refused even when first pid exited ---
python3 "$STATE_PY" "$STATE_FIX" lock acquire --target feat/x --nonblock >/dev/null
set +e
python3 "$STATE_PY" "$STATE_FIX" lock acquire --target feat/x --nonblock 2>/dev/null
EC_LIVE=$?
set -e
python3 "$STATE_PY" "$STATE_FIX" lock release --target feat/x >/dev/null
if [[ "$EC_LIVE" -eq 20 ]]; then
  ok "lock-stale-reclaim: fresh-heartbeat lock refused (exit 20)"
else
  bad "lock-stale-reclaim: fresh-heartbeat lock should refuse ec=20 got $EC_LIVE"
fi

# --- merge-journal-idempotent-replay ---
echo '{"verdict":"running","target":{"branch":"main"},"phases":{"1":{"slug":"alpha","branch":"feat/alpha"}},"mergeJournal":{"phase":"alpha","key":"alpha","startedAt":"2026-01-01T00:00:00Z"},"completedMerges":[]}' \
  > .cursor/sw-deliver-state.json
if python3 "$STATE_PY" "$STATE_FIX" journal complete --phase alpha 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('verdict')=='pass'
"; then
  ok "merge-journal-idempotent-replay: journal complete records completedMerges"
else
  bad "merge-journal-idempotent-replay: journal complete"
fi
if python3 "$STATE_PY" "$STATE_FIX" journal complete --phase alpha 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('note','').startswith('already completed')
"; then
  ok "merge-journal-idempotent-replay: second complete is idempotent"
else
  bad "merge-journal-idempotent-replay: idempotent complete"
fi

# --- deliver-state-scoped-per-branch (PRD 013) ---
mkdir -p .cursor
python3 "$STATE_PY" "$STATE_FIX" lock acquire --target feat/alpha --nonblock >/dev/null
python3 "$STATE_PY" "$STATE_FIX" lock acquire --target feat/beta --nonblock >/dev/null
if [[ -f .cursor/sw-deliver-alpha.lock && -f .cursor/sw-deliver-beta.lock ]]; then
  ok "deliver-state-scoped-per-branch: per-target lock files"
else
  bad "deliver-state-scoped-per-branch: per-target lock files"
fi
python3 "$STATE_PY" "$STATE_FIX" lock release --target feat/alpha >/dev/null
python3 "$STATE_PY" "$STATE_FIX" lock release --target feat/beta >/dev/null

TARGET_BRANCH="feat/scoped-demo"
echo '{"verdict":"running","source_task_list":"docs/prds/099-demo/tasks-099-demo.md","target":{"branch":"feat/scoped-demo","slug":"scoped-demo"}}' \
  > .cursor/sw-deliver-state.json
if python3 "$STATE_PY" "$STATE_FIX" resolve state-path --target "$TARGET_BRANCH" 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['relative'].endswith('sw-deliver-state.scoped-demo.json')
"; then
  ok "deliver-legacy-state-migration: resolves scoped path for target"
else
  bad "deliver-legacy-state-migration: resolves scoped path for target"
fi

if [[ "$FAIL" -ne 0 ]]; then
  echo "state fixtures: FAIL"
  exit 1
fi
echo "state fixtures: PASS"
