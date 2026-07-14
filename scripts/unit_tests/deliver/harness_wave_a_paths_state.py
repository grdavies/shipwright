#!/usr/bin/env python3
"""PRD 068 wave-a-paths-state fixtures (R3–R4)."""
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
  git worktree add -q -b feat/demo-068 "$ORCH"
  mkdir -p "$ORCH/.cursor"
)

ROOT_STATE="$TMP/.cursor/sw-deliver-state.demo-068.json"
ORCH_STATE="$ORCH/.cursor/sw-deliver-state.demo-068.json"
mkdir -p "$(dirname "$ROOT_STATE")" "$(dirname "$ORCH_STATE")"

# --- path-escape-dotdot-fail-closed (R3) ---
if python3 -c "
import sys
from pathlib import Path
sys.path.insert(0, '$ROOT/scripts')
from wave_state import normalize_worktree_path, WorktreePathError
try:
    normalize_worktree_path('../outside', anchor=Path('$TMP'), field='test')
    raise SystemExit(1)
except WorktreePathError:
    raise SystemExit(0)
" 2>/dev/null; then
  ok "path-escape-dotdot-fail-closed"
else
  bad "path-escape-dotdot-fail-closed"
fi

# --- path-normalize-relative-to-absolute (R3) ---
if python3 -c "
import sys
from pathlib import Path
sys.path.insert(0, '$ROOT/scripts')
from wave_state import normalize_worktree_path
anchor = Path('$TMP')
expected = (anchor / '.sw-worktrees/phase-a').resolve()
actual = Path(normalize_worktree_path('.sw-worktrees/phase-a', anchor=anchor, field='phase'))
assert actual == expected
" 2>/dev/null; then
  ok "path-normalize-relative-to-absolute"
else
  bad "path-normalize-relative-to-absolute"
fi

# --- heartbeat-primary-first-shared-updatedAt (R4) ---
BASE_STATE='{"verdict":"running","target":{"branch":"feat/demo-068"},"orchestratorWorktree":{"path":"'"$ORCH"'"}}'
echo "$BASE_STATE" > "$ROOT_STATE"
echo "$BASE_STATE" > "$ORCH_STATE"
(cd "$ORCH" && python3 "$ROOT/scripts/wave_state.py" . state heartbeat --target feat/demo-068 >/dev/null)
PRIMARY_AT=$(python3 -c "import json; print(json.load(open('$ROOT_STATE')).get('updatedAt',''))")
MIRROR_AT=$(python3 -c "import json; print(json.load(open('$ORCH_STATE')).get('updatedAt',''))")
PRIMARY_HB=$(python3 -c "import json; print(json.load(open('$ROOT_STATE')).get('driverHeartbeatAt',''))")
if [[ -n "$PRIMARY_AT" && "$PRIMARY_AT" == "$MIRROR_AT" && "$PRIMARY_HB" == "$PRIMARY_AT" ]]; then
  ok "heartbeat-primary-first-shared-updatedAt"
else
  bad "heartbeat-primary-first-shared-updatedAt"
fi

# --- crash-mid-mirror-resumes-primary (R4) ---
echo '{"verdict":"running","updatedAt":"2026-07-14T10:05:00Z","target":{"branch":"feat/demo-068"},"orchestratorWorktree":{"path":"'"$ORCH"'"}}' > "$ROOT_STATE"
echo '{"verdict":"running","updatedAt":"2026-07-14T10:00:00Z","target":{"branch":"feat/demo-068"},"orchestratorWorktree":{"path":"'"$ORCH"'"}}' > "$ORCH_STATE"
VERDICT=$(cd "$ORCH" && python3 -c "
import sys
from pathlib import Path
sys.path.insert(0, '$ROOT/scripts')
from wave_state import sync_canonical_state_read
print(sync_canonical_state_read(Path('.')).get('updatedAt',''))
")
if [[ "$VERDICT" == "2026-07-14T10:05:00Z" ]]; then
  ok "crash-mid-mirror-resumes-primary"
else
  bad "crash-mid-mirror-resumes-primary (got $VERDICT)"
fi

# --- fresher-mirror-skew-fail-closed (R4) ---
echo '{"verdict":"running","updatedAt":"2026-07-14T09:00:00Z","target":{"branch":"feat/demo-068"},"orchestratorWorktree":{"path":"'"$ORCH"'"}}' > "$ROOT_STATE"
echo '{"verdict":"running","updatedAt":"2026-07-14T10:30:00Z","target":{"branch":"feat/demo-068"},"orchestratorWorktree":{"path":"'"$ORCH"'"}}' > "$ORCH_STATE"
if (cd "$ORCH" && python3 -c "
import sys
from pathlib import Path
sys.path.insert(0, '$ROOT/scripts')
from wave_state import sync_canonical_state_read
try:
    sync_canonical_state_read(Path('.'))
except SystemExit:
    raise SystemExit(0)
raise SystemExit(1)
" 2>/dev/null); then
  ok "fresher-mirror-skew-fail-closed"
else
  bad "fresher-mirror-skew-fail-closed"
fi

# --- repair-mirror-from-primary (R4) ---
echo '{"verdict":"running","updatedAt":"2026-07-14T09:00:00Z","target":{"branch":"feat/demo-068"},"orchestratorWorktree":{"path":"'"$ORCH"'"}}' > "$ROOT_STATE"
echo '{"verdict":"running","updatedAt":"2026-07-14T10:30:00Z","target":{"branch":"feat/demo-068"},"orchestratorWorktree":{"path":"'"$ORCH"'"}}' > "$ORCH_STATE"
(cd "$ORCH" && python3 "$ROOT/scripts/wave_state.py" . state repair-mirror --target feat/demo-068 >/dev/null)
REPAIRED=$(python3 -c "import json; print(json.load(open('$ORCH_STATE')).get('updatedAt',''))")
if [[ "$REPAIRED" == "2026-07-14T09:00:00Z" ]]; then
  ok "repair-mirror-from-primary"
else
  bad "repair-mirror-from-primary (got $REPAIRED)"
fi

if [[ "$FAIL" -eq 0 ]]; then
  echo "wave-a-paths-state fixtures: all passed"
  exit 0
fi
echo "wave-a-paths-state fixtures: $FAIL failure(s)"
exit 1
"""

if __name__ == "__main__":
    raise SystemExit(main())
