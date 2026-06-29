#!/usr/bin/env bash
# PRD 036 Phase 5 — mechanical sourcing audit (R19).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FAIL=0

ok()  { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

LAYOUT="$ROOT/.sw/layout.md"
CONDUCTOR="$ROOT/core/skills/conductor/SKILL.md"
DELIVER_CMD="$ROOT/core/commands/sw-deliver.md"
LOOP_PY="$ROOT/scripts/wave_deliver_loop.py"

if grep -qE 'sw-deliver-state\.<slug>|sw-deliver-runs/<phase-slug>/status\.json' "$LAYOUT" && \
   ! grep -qE 'parallel state store|second state file' "$CONDUCTOR"; then
  ok "no-new-parallel-state-store"
else
  bad "no-new-parallel-state-store"
fi

if grep -q 'scripts/wave.sh deliver-loop' "$CONDUCTOR" && \
   grep -q 'does not maintain parallel state' "$CONDUCTOR" && \
   grep -q 'wave_\*\.py' "$CONDUCTOR"; then
  ok "conductor-delegates-wave-sh"
else
  bad "conductor-delegates-wave-sh"
fi

if grep -q 'save_state' "$LOOP_PY" && \
   grep -q 'compute_next_action' "$LOOP_PY" && \
   ! grep -qE 'hand-edit.*status\.json|manually edit status' "$DELIVER_CMD"; then
  ok "state-transitions-via-wave-py"
else
  bad "state-transitions-via-wave-py"
fi

exit "$FAIL"
