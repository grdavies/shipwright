#!/usr/bin/env python3
"""Ported fixture suite (R27) — embedded harness executed without on-disk shell files."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR.parent))

from _fixture_lib import repo_root
from _harness_patch import patch_source as _patch_source


def main() -> int:
    root = repo_root(__file__)
    env = os.environ.copy()
    env["ROOT"] = str(root)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(root / "scripts" / "test"), str(root / "scripts"), env.get("PYTHONPATH", "")) if p
    )
    src = _patch_source(_SOURCE, root)
    completed = subprocess.run(
        ["bash", "-c", src],
        cwd=str(root),
        env=env,
        shell=False,
    )
    return completed.returncode


_SOURCE = r"""
#!/usr/bin/env bash
# PRD 035 Phase 2 — planning autonomy posture + bounded full-conductor fixtures.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="$ROOT/scripts:${PYTHONPATH:-}"
PY="$ROOT/scripts/planning_autonomy.py"
SCHEMA="$ROOT/core/sw-reference/config.schema.json"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

[[ -f "$PY" ]] || { bad "planning_autonomy.py missing"; exit 1; }

mk_repo() {
  local dest="$1"
  local cfg="${2:-}"
  rm -rf "$dest"
  mkdir -p "$dest/.cursor"
  (
    cd "$dest"
    git init -q
    git config user.email test@test.com
    git config user.name Test
    if [[ -n "$cfg" ]]; then
      cp "$cfg" .cursor/workflow.config.json
    fi
    bash "$ROOT/scripts/shipwright-state.py" init '{}' >/dev/null
  )
}

if python3 - "$SCHEMA" <<'PY'
import json, sys
from pathlib import Path
try:
    import jsonschema
except ImportError:
    sys.exit(0)
schema = json.loads(Path(sys.argv[1]).read_text())
planning = schema["properties"]["planning"]["properties"]
autonomy = planning["autonomy"]
assert autonomy["default"] == "maintenance-only"
assert set(autonomy["enum"]) == {"maintenance-only", "full-conductor"}
fc = planning["fullConductor"]["properties"]
assert fc["mutationBudget"]["default"] == 5
good = {"planning": {"autonomy": "maintenance-only", "fullConductor": {"mutationBudget": 3}}}
jsonschema.validate(good, schema, cls=jsonschema.Draft7Validator)
try:
    jsonschema.validate({"planning": {"autonomy": "unbounded"}}, schema, cls=jsonschema.Draft7Validator)
    raise SystemExit(1)
except jsonschema.ValidationError:
    pass
try:
    jsonschema.validate({"planning": {"autonomy": "full-conductor", "fullConductor": {"extra": 1}}}, schema, cls=jsonschema.Draft7Validator)
    raise SystemExit(1)
except jsonschema.ValidationError:
    pass
PY
then ok "planning-autonomy-config-enum"; else bad "planning-autonomy-config-enum"; fi

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

mk_repo "$TMP/maint"
if OUT=$(cd "$TMP/maint" && python3 "$PY" . evaluate --decision-type graph-bookkeeping) && echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin)['evaluation']; assert d['verdict']=='autonomous' and d['requiresConfirm'] is False"; then
  ok "maintenance-only-default-no-prompts"
else bad "maintenance-only-default-no-prompts"; fi
EC=0
OUT=$(cd "$TMP/maint" && python3 "$PY" . evaluate --decision-type pull-in 2>&1) || EC=$?
if [[ "$EC" -eq 30 ]] && echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin)['evaluation']; assert d['verdict']=='propose'"; then
  ok "maintenance-only-default-no-prompts: content-gated"
else bad "maintenance-only-default-no-prompts: content-gated"; fi

FC_CFG=$(mktemp)
cat > "$FC_CFG" <<'JSON'
{"planning":{"autonomy":"full-conductor","fullConductor":{"confidenceThreshold":0.8,"mutationBudget":2,"undoWindowSeconds":7200}}}
JSON
mk_repo "$TMP/fc" "$FC_CFG"
EC=0
OUT=$(cd "$TMP/fc" && python3 "$PY" . evaluate --decision-type gap-absorb --visibility private 2>&1) || EC=$?
[[ "$EC" -eq 33 ]] && ok "full-conductor-bounded-budget-halt: private-refusal" || bad "full-conductor-bounded-budget-halt: private-refusal"
(cd "$TMP/fc" && python3 "$PY" . auto-decide --candidate-id gap-001 --confidence 0.9 >/dev/null)
(cd "$TMP/fc" && python3 "$PY" . auto-decide --candidate-id gap-002 --confidence 0.91 >/dev/null)
EC=0
OUT=$(cd "$TMP/fc" && python3 "$PY" . auto-decide --candidate-id gap-003 --confidence 0.92 2>&1) || EC=$?
[[ "$EC" -eq 31 ]] && echo "$OUT" | grep -q 'mutation budget' && ok "full-conductor-bounded-budget-halt: budget-halt" || bad "full-conductor-bounded-budget-halt: budget-halt"
(cd "$TMP/fc" && python3 "$PY" . undo --candidate-id gap-001 >/dev/null) && ok "full-conductor-bounded-budget-halt: undo" || bad "full-conductor-bounded-budget-halt: undo"

mk_repo "$TMP/handoff"
EC=0
OUT=$(cd "$TMP/handoff" && python3 "$PY" . check-dispatch --command /sw-deliver 2>&1) || EC=$?
[[ "$EC" -eq 32 ]] && ok "enqueue-handoff-no-nested-dispatch" || bad "enqueue-handoff-no-nested-dispatch"
(cd "$TMP/handoff" && python3 "$PY" . reconcile-complete >/dev/null)
OUT=$(cd "$TMP/handoff" && python3 "$PY" . enqueue-handoff --command "/sw-prd" --reason test)
echo "$OUT" | grep -q 'enqueued' && ok "enqueue-handoff-no-nested-dispatch: handoff-allowed" || bad "enqueue-handoff-no-nested-dispatch: handoff-allowed"
EC=0
OUT=$(cd "$TMP/handoff" && python3 "$PY" . enqueue-handoff --command /sw-tasks 2>&1) || EC=$?
[[ "$EC" -eq 32 ]] && echo "$OUT" | grep -q 'reconcile-dispatch-boundary' && ok "enqueue-handoff-no-nested-dispatch: reconcile-halt" || bad "enqueue-handoff-no-nested-dispatch: reconcile-halt"

mk_repo "$TMP/log"
(cd "$TMP/log" && python3 "$PY" . log-action --kind full-conductor-opt-in --why "pilot opt-in" >/dev/null)
(cd "$TMP/log" && python3 "$PY" . evaluate --decision-type pull-in --override >/dev/null || true)
(cd "$TMP/log" && python3 "$PY" . evaluate --decision-type gap-absorb --accept-frozen-impact >/dev/null || true)
(cd "$TMP/log" && python3 "$PY" . evaluate --decision-type gap-absorb --direct-to-trunk >/dev/null || true)
python3 -c "
import json
from pathlib import Path
state = json.loads(Path('$TMP/log/.cursor/hooks/state/planning-autonomy.json').read_text())
kinds = {e['kind'] for e in state['actionLog']}
assert {'full-conductor-opt-in','override','accept-frozen-impact','direct-to-trunk'} <= kinds
ship = json.loads(Path('$TMP/log/.git/shipwright.json').read_text())
assert len(ship.get('overrides',[])) >= 4
" && ok "autonomy-actions-logged-durable" || bad "autonomy-actions-logged-durable"

rm -f "$FC_CFG"
exit "$FAIL"

"""

if __name__ == "__main__":
    raise SystemExit(main())
