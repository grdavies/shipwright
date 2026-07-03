#!/usr/bin/env python3
"""Ported fixture suite (R27) — embedded harness executed without on-disk shell files."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
_SCRIPTS_ROOT = SCRIPT_DIR.parents[1]
_TEST_DIR = _SCRIPTS_ROOT / "test"
for _entry in (str(_TEST_DIR), str(_SCRIPTS_ROOT)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from _fixture_lib import repo_root
from _harness_patch import harness_subprocess_env as _harness_env
from _harness_patch import patch_source as _patch_source


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
trap 'rm -rf "$TMP"' EXIT
(
  cd "$TMP"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  git commit --allow-empty -q -m init
  git branch -M main
  mkdir -p .cursor docs/prds
  echo '{"defaultBaseBranch":"main"}' > .cursor/workflow.config.json
  printf '%s\n' '| # | slug | prd | tasks | status |' '|---|------|-----|-------|--------|' '| 049 | operator-worktree-contract | link | link | in-progress |' > docs/prds/INDEX.md
  echo '{"updatedAt":"2026-01-01T00:00:00Z","verdict":"running","target":{"branch":"feat/demo-049"},"prd_number":"049","phases":{"1":{"status":"pending"}}}' > .cursor/sw-deliver-state.demo-049.json
  mkdir -p .cursor/sw-deliver-runs
  echo '{"updatedAt":"2026-01-01T00:00:00Z","runs":[{"slug":"demo-049","verdict":"running","statePath":".cursor/sw-deliver-state.demo-049.json"}]}' > .cursor/sw-deliver-runs/index.json
  git add -A
  git commit -q -m seed
)

OUT=$(cd "$TMP" && python3 "$ROOT/scripts/wave_living_docs.py" "$TMP" reconcile --commit 2>&1) || EC=$?
EC=${EC:-0}
if [[ "$EC" -ne 0 ]] && echo "$OUT" | grep -q "in-flight deliver run"; then
  ok "deliver-cwd-guard-blocks-main-living-doc"
else
  bad "deliver-cwd-guard-blocks-main-living-doc (ec=$EC)"
  echo "$OUT"
fi

echo 'not-json{{' > "$TMP/.cursor/sw-deliver-runs/index.json"
OUT2=$(cd "$TMP" && python3 "$ROOT/scripts/deliver_cwd_guard.py" 2>&1) || EC2=$?
EC2=${EC2:-0}
if [[ "$EC2" -ne 0 ]] && echo "$OUT2" | grep -qi remediation; then
  ok "deliver-cwd-guard-corrupt-index-fail-closed"
else
  bad "deliver-cwd-guard-corrupt-index-fail-closed (ec=$EC2)"
  echo "$OUT2"
fi

if [[ "$FAIL" -eq 0 ]]; then
  echo "deliver-cwd-guard fixtures: all passed"
  exit 0
fi
echo "deliver-cwd-guard fixtures: $FAIL failure(s)"
exit 1
"""
if __name__ == "__main__":
    raise SystemExit(main())
