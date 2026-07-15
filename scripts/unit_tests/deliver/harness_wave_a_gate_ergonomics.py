#!/usr/bin/env python3
"""PRD 069 wave-a-gate-ergonomics fixtures (R3)."""
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
    completed = subprocess.run(
        ["bash", "-c", src],
        cwd=str(root),
        env=env,
        shell=False,
    )
    return completed.returncode


_SOURCE = r"""
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="$ROOT/scripts:$PYTHONPATH"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

TMP=$(mktemp -d)
ORCH="$TMP/orch"
trap 'rm -rf "$TMP"' EXIT
(
  cd "$TMP"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  git commit --allow-empty -q -m init
  git branch -M main
  mkdir -p .cursor
  git worktree add -q -b feat/demo-069 "$ORCH"
  mkdir -p "$ORCH/.cursor"
)

ROOT_STATE="$TMP/.cursor/sw-deliver-state.demo-069.json"
ORCH_STATE="$ORCH/.cursor/sw-deliver-state.demo-069.json"
mkdir -p "$(dirname "$ROOT_STATE")" "$(dirname "$ORCH_STATE")"

# --- skew-repair-auto (R3) ---
echo '{"verdict":"running","updatedAt":"2026-07-14T09:00:00Z","target":{"branch":"feat/demo-069"},"orchestratorWorktree":{"path":"'"$ORCH"'"}}' > "$ROOT_STATE"
echo '{"verdict":"running","updatedAt":"2026-07-14T10:30:00Z","target":{"branch":"feat/demo-069"},"orchestratorWorktree":{"path":"'"$ORCH"'"}}' > "$ORCH_STATE"
(cd "$ORCH" && python3 -c "
import sys
from pathlib import Path
sys.path.insert(0, '$ROOT/scripts')
from wave_state import ensure_canonical_state_synced
ensure_canonical_state_synced(Path('.'))
" >/dev/null)
REPAIRED=$(python3 -c "import json; print(json.load(open('$ORCH_STATE')).get('updatedAt',''))")
if [[ "$REPAIRED" == "2026-07-14T09:00:00Z" ]]; then
  ok "skew-repair-auto"
else
  bad "skew-repair-auto (got $REPAIRED)"
fi

# --- forgery-fail-closed (R3) ---
FORGED='{"verdict":"merge-ready-green","phase":"alpha","phaseMode":true,"head":"0000000000000000000000000000000000000001","provenanceMarker":"deadbeef","writtenAt":"2020-01-01T00:00:00Z"}'
if ! python3 "$ROOT/scripts/status_integrity.py" validate --path /dev/stdin <<<"$FORGED" >/dev/null 2>&1; then
  ok "forgery-fail-closed"
else
  bad "forgery-fail-closed"
fi

# --- status-atomic-write-gap-check (R3) ---
GAP_DIR="$TMP/gap-run"
mkdir -p "$GAP_DIR"
if python3 "$ROOT/scripts/gap-check-gate.py" write "$TMP" --phase-slug gap-alpha --verdict pass --head 0000000000000000000000000000000000000001 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('action')=='gap-check-write'
" && test -f "$TMP/.cursor/sw-deliver-runs/gap-alpha/gap-check.status.json"; then
  ok "status-atomic-write-gap-check"
else
  bad "status-atomic-write-gap-check"
fi

# --- status-remediation-present (R3) ---
if python3 "$ROOT/scripts/status_integrity.py" validate --path /dev/stdin <<<"$FORGED" 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('verdict')=='fail'
assert d.get('remediation')
"; then
  ok "status-remediation-present"
else
  bad "status-remediation-present"
fi

if [[ "$FAIL" -eq 0 ]]; then
  echo "wave-a-gate-ergonomics fixtures: all passed"
  exit 0
fi
echo "wave-a-gate-ergonomics fixtures: $FAIL failure(s)"
exit 1
"""

if __name__ == "__main__":
    raise SystemExit(main())
