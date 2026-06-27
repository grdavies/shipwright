#!/usr/bin/env bash
# PRD 019 pre-work memory search recorder fixtures (R6, R7).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WAVE="$ROOT/scripts/wave.sh"
FAIL=0

ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

FIX_DIR="$(mktemp -d)"
trap 'rm -rf "$FIX_DIR"' EXIT

mkdir -p "$FIX_DIR/.cursor"
cp "$ROOT/.cursor/workflow.config.json" "$FIX_DIR/.cursor/" 2>/dev/null || true

pushd "$FIX_DIR" >/dev/null
git init -q
git config user.email "fixture@shipwright.local"
git config user.name "fixture"

# memory-prework-breadcrumb-audited + degrade-open offline path
if OUT=$(bash "$WAVE" memory prework record --surface sw-execute --offline 2>/dev/null) && \
   echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('verdict')=='pass'
assert d.get('outcome')=='memory:offline'
assert d.get('nonce')
"; then
  ok "memory-prework-degrade-open"
else
  bad "memory-prework-degrade-open"
fi

if [[ -f .cursor/hooks/state/memory-prework-search.json ]] && \
   grep -q 'memory:offline' .cursor/hooks/state/memory-prework-search.json && \
   [[ -f .cursor/sw-deliver-runs/run.log ]]; then
  ok "memory-prework-breadcrumb-audited"
else
  bad "memory-prework-breadcrumb-audited"
fi

# memory:none path (reachable in-repo provider)
rm -f .cursor/hooks/state/memory-prework-search.json .cursor/sw-deliver-runs/run.log
mkdir -p .cursor/sw-memory/memories
echo in-repo > .cursor/sw-memory.provider
if OUT=$(bash "$WAVE" memory prework record --surface sw-execute --hit-count 0 2>/dev/null) && \
   echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('outcome')=='memory:none'
"; then
  ok "memory-prework-none-breadcrumb"
else
  bad "memory-prework-none-breadcrumb"
fi

popd >/dev/null

if [[ "$FAIL" -eq 0 ]]; then
  echo "run-memory-prework-fixtures: PASS"
else
  echo "run-memory-prework-fixtures: FAIL"
  exit 1
fi
