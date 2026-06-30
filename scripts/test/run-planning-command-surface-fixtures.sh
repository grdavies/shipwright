#!/usr/bin/env bash
# PRD 035 phase 4 — planning command surface finalization fixtures (R15).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=scripts/test/fixture-lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/fixture-lib.sh"
GRAPH="$ROOT/scripts/planning-graph.sh"
CORE_GRAPH="$ROOT/core/scripts/planning-graph.sh"
SW_DOC="$(content_path commands/sw-doc.md)"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

check() {
  local name="$1" file="$2" pattern="$3"
  if grep -qE "$pattern" "$file" 2>/dev/null; then ok "$name"; else bad "$name"; fi
}

[[ -x "$GRAPH" ]] || chmod +x "$GRAPH"

# --- command-surface-wired: sw-doc.md ---
check "sw-doc-reconciler-entry" "$SW_DOC" "planning-graph\.sh reconcile"
check "sw-doc-scheduler-entry" "$SW_DOC" "/sw-deliver next"
check "sw-doc-posture-config" "$SW_DOC" "planning\.autonomy"
check "sw-doc-paths-helper" "$SW_DOC" "planning_paths\.sh"
check "sw-doc-no-sw-plan" "$SW_DOC" "no top-level \`/sw-plan\`"

# --- command-surface-wired: planning-graph.sh ---
check "planning-graph-next-subcommand" "$GRAPH" 'next\)'
check "planning-graph-posture-subcommand" "$GRAPH" 'posture\)'
check "planning-graph-paths-subcommand" "$GRAPH" 'paths\)'
check "planning-graph-help-reconcile" "$GRAPH" "planning-graph.sh reconcile"
check "planning-graph-help-next" "$GRAPH" "planning-graph.sh next"
check "planning-graph-help-posture" "$GRAPH" "planning-graph.sh posture"

if diff -q "$GRAPH" "$CORE_GRAPH" >/dev/null 2>&1; then
  ok "planning-graph-core-parity"
else
  bad "planning-graph-core-parity"
fi

# --- command-surface-wired: live posture readback ---
if OUT=$(bash "$GRAPH" posture 2>/dev/null) && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('verdict')=='ok'
posture=d['posture']
assert posture['mode']=='maintenance-only'
"; then
  ok "command-surface-wired: posture-default"
else
  bad "command-surface-wired: posture-default"
fi

# --- command-surface-wired: paths helper delegation ---
if OUT=$(bash "$GRAPH" paths dirs 2>/dev/null) && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('verdict')=='pass'
assert 'planningDir' in d.get('dirs',{})
"; then
  ok "command-surface-wired: paths-dirs"
else
  bad "command-surface-wired: paths-dirs"
fi

exit "$FAIL"
