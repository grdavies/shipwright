#!/usr/bin/env python3
"""PRD 049 R4 — canonical state read from orchestrator cwd fixtures."""
from __future__ import annotations

import os
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
  git worktree add -q "$ORCH" -b feat/demo-049
  mkdir -p "$ORCH/.cursor"
)

ROOT_STATE="$TMP/.cursor/sw-deliver-state.demo-049.json"
ORCH_STATE="$ORCH/.cursor/sw-deliver-state.demo-049.json"
mkdir -p "$(dirname "$ROOT_STATE")" "$(dirname "$ORCH_STATE")"

write_states() {
  local root_updated="$1"
  local orch_updated="$2"
  local root_verdict="$3"
  local orch_verdict="$4"
  cat > "$ROOT_STATE" <<EOF
{"verdict":"$root_verdict","updatedAt":"$root_updated","target":{"branch":"feat/demo-049"},"orchestratorWorktree":{"path":"$ORCH"}}
EOF
  cat > "$ORCH_STATE" <<EOF
{"verdict":"$orch_verdict","updatedAt":"$orch_updated","target":{"branch":"feat/demo-049"},"orchestratorWorktree":{"path":"$ORCH"}}
EOF
}

write_states "2026-06-01T12:00:00Z" "2026-06-01T12:00:00Z" running complete
VERDICT=$(cd "$ORCH" && python3 -c "
import sys
from pathlib import Path
sys.path.insert(0, '$ROOT/scripts')
from wave_state import sync_canonical_state_read
print(sync_canonical_state_read(Path('.')).get('verdict',''))
")
if [[ "$VERDICT" == "running" ]]; then
  ok "terminal-reads-repo-root-state-from-orchestrator-cwd"
else
  bad "terminal-reads-repo-root-state-from-orchestrator-cwd (verdict=$VERDICT)"
fi

write_states "2026-06-01T12:00:00Z" "2026-06-01T12:05:00Z" running running
if (cd "$ORCH" && python3 -c "
import sys
from pathlib import Path
sys.path.insert(0, '$ROOT/scripts')
from wave_state import sync_canonical_state_read
sync_canonical_state_read(Path('.'))
print('pass')
"); then
  ok "terminal-state-skew-boundary-equal-passes"
else
  bad "terminal-state-skew-boundary-equal-passes"
fi

write_states "2026-06-01T12:00:00Z" "2026-06-01T12:05:01Z" running running
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
  ok "terminal-state-skew-boundary-over-refuses"
else
  bad "terminal-state-skew-boundary-over-refuses"
fi

if [[ "$FAIL" -eq 0 ]]; then
  echo "terminal-state-read fixtures: all passed"
  exit 0
fi
echo "terminal-state-read fixtures: $FAIL failure(s)"
exit 1
"""

if __name__ == "__main__":
    raise SystemExit(main())
