#!/usr/bin/env python3
"""PRD 061 task 1.1 — facade API surface + IssuesClient allowlist conformance (R1, R2, R2a, R25)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
_SCRIPTS_ROOT = SCRIPT_DIR.parents[1]
_TEST_DIR = _SCRIPTS_ROOT / "test"
for _entry in (str(_TEST_DIR), str(_SCRIPTS_ROOT)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from _sw.vendor_paths import repo_root
from unit_tests._harness_runtime import harness_subprocess_env as _harness_env
from unit_tests._harness_runtime import patch_source as _patch_source


def main() -> int:
    root = repo_root(__file__)
    env = _harness_env(root)
    src = _patch_source(_SOURCE, root)
    completed = subprocess.run(["bash", "-c", src], cwd=str(root), env=env, shell=False)
    return completed.returncode


_SOURCE = r"""
#!/usr/bin/env bash
# PRD 061 phase 1 task 1.1 — facade API + IssuesClient allowlist (R1, R2, R2a, R25).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="$ROOT/scripts:${PYTHONPATH:-}"
PY="$ROOT/scripts/planning_store.py"
PROBE="$ROOT/scripts/test/fixtures/planning-facade-bypass/probe.py"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

# --- facade-api-surface (R2) ---
if OUT=$(python3 "$PY" --root "$ROOT" list-facade) && \
   echo "$OUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d.get('verdict') == 'ok'
ops = {o['name'] for o in d.get('operations', [])}
required = {
    'put', 'get', 'exists', 'materialize',
    'derive_unit_status', 'progress_update',
    'close_delivery_units', 'comment_sync', 'projection_refresh',
}
missing = required - ops
assert not missing, f'missing facade ops: {missing}'
shipped = {o['name'] for o in d.get('operations', []) if o.get('status') == 'shipped'}
for name in ('put', 'get', 'exists', 'materialize', 'close_delivery_units'):
    assert name in shipped, f'{name} must be shipped'
"; then
  ok "facade-api-surface"
else
  bad "facade-api-surface"
fi

# --- allowlist-static-import (R2a) ---
if OUT=$(python3 "$PY" --root "$ROOT" lint-facade-imports --path scripts/planning_store.py) && \
   echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('verdict')=='pass'"; then
  ok "allowlist-static-import:planning-store-allowed"
else
  bad "allowlist-static-import:planning-store-allowed"
fi
set +e
PROBE_OUT=$(python3 "$PY" --root "$ROOT" lint-facade-imports --path "$PROBE" 2>/dev/null)
PROBE_RC=$?
set -e
if [[ "$PROBE_RC" -eq 20 ]] && echo "$PROBE_OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('verdict')=='fail'
viol = d.get('violations', [])
assert any('probe.py' in v.get('path','') for v in viol)
"; then
  ok "allowlist-static-import:probe-detected"
else
  bad "allowlist-static-import:probe-detected"
fi

# --- facade-bypass-fail-closed (R1) ---
set +e
LINT_OUT=$(python3 "$PY" --root "$ROOT" lint-facade-imports 2>/dev/null)
LINT_RC=$?
set -e
if [[ "$LINT_RC" -eq 20 ]] && echo "$LINT_OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('verdict')=='fail'
paths = {v.get('path') for v in d.get('violations', [])}
expected = {
    'scripts/planning_discover.py',
    'scripts/planning_scheduler.py',
    'scripts/planning_unit_status.py',
}
missing = expected - paths
assert not missing, f'lint missed baseline violators: {missing}'
"; then
  ok "facade-bypass-fail-closed"
else
  bad "facade-bypass-fail-closed"
fi

# --- conformance-harness-floor (R25) ---
if [[ -f "$ROOT/scripts/unit_tests/planning/harness_planning_061_facade.py" ]]; then
  ok "conformance-harness-floor"
else
  bad "conformance-harness-floor"
fi

exit $FAIL
"""

if __name__ == "__main__":
    raise SystemExit(main())
