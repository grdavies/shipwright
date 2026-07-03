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
LIFE="$ROOT/scripts/wave_lifecycle.py"
LOOP="$ROOT/scripts/wave.py"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
cd "$TMP"
git init -q
git config user.email test@test.com
git config user.name Test
git commit --allow-empty -q -m init
git branch -M main
git checkout -q -b feat/contract-fixture
mkdir -p .cursor docs/prds/049-fixture
cat > .cursor/workflow.config.json <<'JSON'
{"defaultBaseBranch":"main","planningDir":"docs/prds"}
JSON
cat > .cursor/sw-deliver-plan.json <<'JSON'
{"mode":"phase","target":{"type":"feat","slug":"contract-fixture","branch":"feat/contract-fixture"},"items":[{"id":"1","slug":"alpha","title":"A","branch":"feat/contract-fixture-phase-alpha"}],"waves":[["1"]]}
JSON
git add -A && git commit -q -m seed

# Primary checkout returns to main (operator shell)
git checkout -q main

# Orchestrator provision + one deliver-loop mechanical tick from repo root
python3 "$LIFE" "$TMP" orchestrator provision --target feat/contract-fixture >/dev/null
STATE_FILE=$(ls "$TMP/.cursor"/sw-deliver-state.*.json 2>/dev/null | head -1)
if [[ -n "$STATE_FILE" && -f "$STATE_FILE" ]]; then
  ok "deliver-worktree-contract-repo-root-state-updated"
else
  bad "deliver-worktree-contract-repo-root-state-updated"
fi

BR=$(git -C "$TMP" rev-parse --abbrev-ref HEAD)
if [[ "$BR" == "main" ]]; then
  ok "deliver-worktree-contract-primary-on-default-base"
else
  bad "deliver-worktree-contract-primary-on-default-base (branch=$BR)"
fi

if git -C "$TMP" diff --quiet main -- . ':!.cursor' 2>/dev/null || [[ -z $(git -C "$TMP" diff --name-only main -- . ':!.cursor' 2>/dev/null) ]]; then
  ok "deliver-worktree-contract-main-tracked-clean"
else
  bad "deliver-worktree-contract-main-tracked-clean"
  git -C "$TMP" diff --name-only main -- . ':!.cursor' || true
fi

# Negative: guard refuses guarded surface from primary during verdict:running
mkdir -p "$TMP/.cursor/sw-deliver-runs"
echo '{"updatedAt":"2026-01-01T00:00:00Z","verdict":"running","target":{"branch":"feat/contract-fixture"}}' > "$TMP/.cursor/sw-deliver-state.contract-fixture.json"
echo '{"updatedAt":"2026-01-01T00:00:00Z","runs":[{"slug":"contract-fixture","verdict":"running","statePath":".cursor/sw-deliver-state.contract-fixture.json"}]}' > "$TMP/.cursor/sw-deliver-runs/index.json"
OUT=$(cd "$TMP" && python3 "$ROOT/scripts/reconcile.py" reconcile 2>&1) || EC=$?
EC=${EC:-0}
if [[ "$EC" -ne 0 ]] && echo "$OUT" | grep -qi remediation; then
  ok "deliver-worktree-contract-guard-refusal-negative"
else
  bad "deliver-worktree-contract-guard-refusal-negative (ec=$EC)"
  echo "$OUT"
fi

if [[ "$FAIL" -eq 0 ]]; then
  echo "deliver-worktree-contract fixtures: all passed"
  exit 0
fi
echo "deliver-worktree-contract fixtures: $FAIL failure(s)"
exit 1
"""
if __name__ == "__main__":
    raise SystemExit(main())
