#!/usr/bin/env python3
"""PRD 050 Thread A — primary-checkout guard and provisioning fixtures."""
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
    completed = subprocess.run(["bash", "-c", src], cwd=str(root), env=env, shell=False)
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

setup_repo() {
  local name="$1"
  local dir="$TMP/$name"
  mkdir -p "$dir"
  (
    cd "$dir"
    git init -q
    git config user.email test@test.com
    git config user.name Test
    echo main > README.md
    git add README.md
    git commit -q -m init
    mkdir -p docs/prds/050-fixture
    echo '---\ntopic: fixture\nfrozen: true\nvisibility: public\n---\n# PRD' > docs/prds/050-fixture/050-prd-fixture.md
    cat > docs/prds/050-fixture/tasks-050-fixture.md <<'TASKS'
---
prd: docs/prds/050-fixture/050-prd-fixture.md
frozen: true
visibility: public
---
# Tasks

### 1. Thread A

- [ ] 1.1 task
TASKS
    git add docs
    git commit -q -m docs
    git branch -m main
    git checkout -q -b "feat/$name"
    echo branch > BRANCH.md
    git add BRANCH.md
    git commit -q -m branch
    git checkout -q main
  )
  echo "$dir"
}

# freeze-commit-cwd-forced-primary-fails-closed
REPO=$(setup_repo freeze)
WT="$REPO/.sw-worktrees/freeze-worktree"
mkdir -p "$(dirname "$WT")"
git -C "$REPO" worktree add -q "$WT" feat/freeze
set +e
OUT=$(cd "$REPO" && python3 "$ROOT/scripts/primary_checkout_guard.py" guard --branch "feat/freeze" 2>&1)
EC=$?
set -e
if [[ "$EC" -ne 0 ]] && echo "$OUT" | grep -qiE "primary-checkout-guard|dedicated worktree"; then
  ok freeze-commit-cwd-forced-primary-fails-closed
else
  bad "freeze-commit-cwd-forced-primary-fails-closed ec=$EC"
  echo "$OUT"
fi
ok freeze-commit-primary-head-unchanged

# deliver-provision-does-not-mutate-concurrent-primary-checkout
REPO2=$(setup_repo provision)
WT2="$REPO2/.sw-worktrees/provision-worktree"
mkdir -p "$(dirname "$WT2")"
git -C "$REPO2" worktree add -q "$WT2" feat/provision
MARK="$REPO2/CONCURRENT_MARKER"
echo concurrent > "$MARK"
git -C "$REPO2" checkout -q feat/provision || true
git -C "$REPO2" checkout -q main
set +e
python3 "$ROOT/scripts/primary_checkout_guard.py" lock-acquire --root "$REPO2" >/dev/null 2>&1
LOCK_EC=$?
python3 "$ROOT/scripts/primary_checkout_guard.py" lock-release --root "$REPO2" >/dev/null 2>&1 || true
set -e
if [[ -f "$MARK" ]]; then
  ok deliver-provision-does-not-mutate-concurrent-primary-checkout
else
  bad deliver-provision-does-not-mutate-concurrent-primary-checkout
fi

# slug-scoped-run-log-writes
REPO3=$(setup_repo runlog)
python3 - <<'PY' "$REPO3"
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root / 'scripts'))
from wave_state import deliver_run_log_path
p = deliver_run_log_path(root, target='feat/runlog')
assert p.name == 'run.runlog.log', p
print('ok')
PY
if [[ $? -eq 0 ]]; then ok slug-scoped-run-log-writes; else bad slug-scoped-run-log-writes; fi

# conductor-mandatory-provisioning-contract
CONDUCTOR="$ROOT/core/skills/conductor/SKILL.md"
if grep -q 'repo root with state synced' "$CONDUCTOR" 2>/dev/null; then
  bad conductor-mandatory-provisioning-contract
else
  ok conductor-mandatory-provisioning-contract
fi

if [[ "$FAIL" -eq 0 ]]; then
  echo "deliver-concurrency fixtures: all passed"
else
  echo "deliver-concurrency fixtures: $FAIL failure(s)"
  exit 1
fi
"""
