#!/usr/bin/env python3
"""PRD 049 R5 — end-to-end operator worktree contract fixtures."""
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
LOOP_PY="$ROOT/scripts/wave_deliver_loop.py"
LCY="$ROOT/scripts/wave_lifecycle.py"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

TARGET="feat/demo-049"
SLUG="demo-049"
STATE_REL=".cursor/sw-deliver-state.${SLUG}.json"
MAIN_TREE_BEFORE=""

setup_repo() {
  cd "$TMP"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  echo "tracked-on-main" >README.md
  git add README.md
  git commit -q -m "init on main"
  git branch -M main
  MAIN_TREE_BEFORE="$(git rev-parse HEAD^{tree})"

  git checkout -q -b "$TARGET"
  mkdir -p docs/prds
  printf '%s\n' '| # | slug | prd | tasks | status |' '|---|------|-----|-------|--------|' '| 049 | operator-worktree-contract | link | link | not-started |' >docs/prds/INDEX.md
  git add docs/prds/INDEX.md
  git commit -q -m "feature seed"

  git checkout -q main

  ln -s "$ROOT/scripts" scripts
  ln -s "$ROOT/core" core

  mkdir -p .cursor docs/prds
  printf '%s\n' '| # | slug | prd | tasks | status |' '|---|------|-----|-------|--------|' '| 049 | operator-worktree-contract | link | link | not-started |' >docs/prds/INDEX.md

  cat >.cursor/workflow.config.json <<'JSON'
{"defaultBaseBranch":"main","review":{"provider":"none"},"checks":{"treatNeutralAsPass":true}}
JSON

  cat >.cursor/sw-deliver-plan.json <<JSON
{
  "verdict": "pass",
  "mode": "phase",
  "prd_number": "049",
  "source_task_list": "docs/prds/049-operator-worktree-contract-and-cwd-guard/tasks-049.md",
  "target": {"type": "feat", "slug": "${SLUG}", "branch": "${TARGET}"},
  "items": [
    {"id": "1", "slug": "alpha", "title": "Alpha", "branch": "${TARGET}-phase-alpha"}
  ],
  "edges": [],
  "waves": [["1"]]
}
JSON

  NOW_TS=$(python3 -c "from datetime import datetime,timezone; print(datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))")

  cat >"$STATE_REL" <<JSON
{
  "verdict": "running",
  "prd_number": "049",
  "updatedAt": "2026-01-01T00:00:00Z",
  "target": {"type": "feat", "slug": "${SLUG}", "branch": "${TARGET}"},
  "source_task_list": "docs/prds/049-operator-worktree-contract-and-cwd-guard/tasks-049.md",
  "currentWave": 1,
  "nextAction": "orchestrator-provision",
  "driverHeartbeatAt": "$NOW_TS",
  "specSeed": {"skipped": true},
  "baseCapture": {"skipped": true},
  "twoTierLifecycle": {"wave": "pending", "phases": {}},
  "phases": {
    "1": {"id": "1", "slug": "alpha", "status": "pending", "branch": "${TARGET}-phase-alpha"}
  }
}
JSON

  mkdir -p .cursor/sw-deliver-runs
  echo '{"updatedAt":"2026-01-01T00:00:00Z","runs":[{"slug":"'"${SLUG}"'","verdict":"running","statePath":"'"${STATE_REL}"'"}]}' \
    >.cursor/sw-deliver-runs/index.json
}

assert_primary_on_main() {
  local branch
  branch="$(git -C "$TMP" branch --show-current)"
  if [[ "$branch" == "main" ]]; then
    ok "deliver-worktree-contract: primary checkout on defaultBaseBranch"
  else
    bad "deliver-worktree-contract: primary checkout on defaultBaseBranch (branch=$branch)"
  fi
}

assert_main_tracked_clean() {
  local tree_now tracked_dirty
  tree_now="$(git -C "$TMP" rev-parse HEAD^{tree})"
  if [[ "$tree_now" == "$MAIN_TREE_BEFORE" ]]; then
    ok "deliver-worktree-contract: no tracked files on main modified"
  else
    bad "deliver-worktree-contract: no tracked files on main modified"
    git -C "$TMP" diff "$MAIN_TREE_BEFORE" HEAD --stat || true
  fi
  tracked_dirty="$(git -C "$TMP" status --porcelain --untracked-files=no)"
  if [[ -z "$tracked_dirty" ]]; then
    ok "deliver-worktree-contract: primary checkout tracked tree clean"
  else
    bad "deliver-worktree-contract: primary checkout tracked tree clean"
    echo "$tracked_dirty"
  fi
}

assert_repo_root_state_updated() {
  local before after
  before="2026-01-01T00:00:00Z"
  after="$(python3 -c "
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
data = json.loads(p.read_text())
print(data.get('updatedAt',''))
" "$TMP/$STATE_REL")"
  if [[ -n "$after" && "$after" != "$before" ]]; then
    ok "deliver-worktree-contract: repo-root scoped state updated"
  else
    bad "deliver-worktree-contract: repo-root scoped state updated (updatedAt=$after)"
  fi
  if python3 -c "
import json, sys
from pathlib import Path
data = json.loads(Path(sys.argv[1]).read_text())
assert data.get('orchestratorWorktree', {}).get('path')
assert data.get('verdict') == 'running'
" "$TMP/$STATE_REL"; then
    ok "deliver-worktree-contract: scoped state carries orchestrator + running verdict"
  else
    bad "deliver-worktree-contract: scoped state carries orchestrator + running verdict"
  fi
}

assert_guard_refusal() {
  local out ec
  set +e
  out=$(cd "$TMP" && python3 "$ROOT/scripts/wave_living_docs.py" "$TMP" reconcile --commit 2>&1)
  ec=$?
  set -e
  if [[ "$ec" -ne 0 ]] && echo "$out" | grep -qi remediation; then
    ok "deliver-worktree-contract: R3 guard refuses primary checkout during in-flight run"
  else
    bad "deliver-worktree-contract: R3 guard refuses primary checkout during in-flight run (ec=$ec)"
    echo "$out"
  fi
}

setup_repo

if ! OUT=$(python3 "$LCY" "$TMP" orchestrator provision --plan .cursor/sw-deliver-plan.json 2>/dev/null); then
  bad "deliver-worktree-contract: orchestrator provision"
  echo "$OUT"
else
  echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('action')=='orchestrator-provision'
assert d.get('path')
" && ok "deliver-worktree-contract: orchestrator provision" || bad "deliver-worktree-contract: orchestrator provision payload"
fi

assert_primary_on_main

if ! OUT=$(python3 "$LOOP_PY" "$TMP" deliver-loop --max-steps 1 2>/dev/null); then
  bad "deliver-worktree-contract: deliver-loop tick"
  echo "$OUT"
else
  echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('action')=='deliver-loop'
assert d.get('stepsTaken')
" && ok "deliver-worktree-contract: deliver-loop tick" || bad "deliver-worktree-contract: deliver-loop tick payload"
fi

assert_repo_root_state_updated
assert_primary_on_main
assert_main_tracked_clean
assert_guard_refusal

if [[ "$FAIL" -eq 0 ]]; then
  echo "deliver-worktree-contract fixtures: all passed"
  exit 0
fi
echo "deliver-worktree-contract fixtures: $FAIL failure(s)"
exit 1
"""

if __name__ == "__main__":
    raise SystemExit(main())
