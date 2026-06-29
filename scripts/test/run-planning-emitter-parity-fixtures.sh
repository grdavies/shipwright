#!/usr/bin/env bash
# PRD 033 phase 6 — emitter/copy-to-core parity for planning scheduler artifacts (R24).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }
GEN="python3 -m sw"

SCRIPTS_033=(
  planning_graph.py
  planning_reconcile.py
  planning_deliver_gate.py
  planning_gap_capture.py
  planning_lifecycle.py
)

# --- emitter-parity-planning-autonomy (R24) ---
for rel in "${SCRIPTS_033[@]}"; do
  if [[ -f "$ROOT/scripts/$rel" && -f "$ROOT/core/scripts/$rel" ]] && cmp -s "$ROOT/scripts/$rel" "$ROOT/core/scripts/$rel"; then
    :
  else
    bad "emitter-parity-planning-autonomy: core/scripts/$rel"
  fi
done
[[ "$FAIL" -eq 0 ]] && ok "emitter-parity-planning-autonomy: copy-to-core parity"

python3 -c "
import json
from pathlib import Path
for p in (Path('$ROOT/.sw/config.schema.json'), Path('$ROOT/core/sw-reference/config.schema.json')):
    s=json.loads(p.read_text())
    pa=s['properties']['planning']['properties']['autonomy']
    assert pa['default']=='maintenance-only'
    assert 'full-conductor' in pa['enum']
" && ok "emitter-parity-planning-autonomy: schema stub" || bad "emitter-parity-planning-autonomy: schema stub"

$GEN generate --all >/dev/null 2>&1 || bad "emitter-parity-planning-autonomy: generate failed"
for dist in "$ROOT/dist/cursor" "$ROOT/dist/claude-code"; do
  for rel in "${SCRIPTS_033[@]}"; do
    [[ -f "$dist/scripts/$rel" ]] || bad "emitter-parity-planning-autonomy: missing $dist/scripts/$rel"
  done
  for schema in .sw/config.schema.json core/sw-reference/config.schema.json; do
  if [[ -f "$dist/$schema" ]]; then
    python3 -c "import json; json.load(open('$dist/$schema'))" || bad "emitter-parity-planning-autonomy: invalid $dist/$schema"
  fi
  done
done
[[ "$FAIL" -eq 0 ]] && ok "emitter-parity-planning-autonomy: dist propagation"

bash "$ROOT/scripts/test/run-emitter-fixtures.sh" >/dev/null 2>&1 && ok "emitter-parity-planning-autonomy: emitter-freshness" || bad "emitter-parity-planning-autonomy: emitter-freshness"

exit "$FAIL"
