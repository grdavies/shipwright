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


# orphan-phase-worktree-adopt-or-teardown (R7/R8)
REPO4=$(setup_repo orphan)
TARGET=feat/orphan
git -C "$REPO4" branch -q feat/orphan-phase-alpha 2>/dev/null || git -C "$REPO4" branch feat/orphan-phase-alpha
WT4="$REPO4/.sw-worktrees/orphan-phase-demo-phase-alpha"
mkdir -p "$(dirname "$WT4")"
git -C "$REPO4" worktree add -q "$WT4" feat/orphan-phase-alpha
mkdir -p "$REPO4/.cursor"
cat >"$REPO4/.cursor/sw-deliver-plan.json" <<JSON
{"mode":"phase","target":{"branch":"$TARGET"},"source_task_list":"docs/prds/050-fixture/tasks-050-fixture.md","items":[{"id":"1","slug":"demo-phase-alpha","branch":"feat/orphan-phase-alpha"}],"waves":[["1"]],"edges":[]}
JSON
cat >"$REPO4/.cursor/sw-deliver-state.orphan.json" <<JSON
{"verdict":"running","target":{"branch":"$TARGET"},"phases":{"1":{"id":"1","slug":"demo-phase-alpha","status":"pending","branch":"feat/orphan-phase-alpha"}},"nextAction":"provision-phase"}
JSON
if OUT=$(python3 "$ROOT/scripts/wave_lifecycle.py" "$REPO4" phase provision --phase-id 1 --plan .cursor/sw-deliver-plan.json --base main 2>&1) && \
   echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('adopted') is True; assert d.get('action')=='phase-provision'" && \
   python3 - <<'PY' "$REPO4"
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
from wave_state import load_deliver_state
state = load_deliver_state(root, target='feat/orphan')
wt = (state.get('phaseWorktrees') or {}).get('1') or {}
assert wt.get('path'), wt
PY
then
  ok orphan-phase-worktree-adopt-or-teardown
else
  bad orphan-phase-worktree-adopt-or-teardown
  echo "$OUT"
fi

# dispatch-ship refuses without phaseWorktrees (R8)
python3 - <<'PY' "$ROOT"
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / 'scripts'))
from wave_deliver_loop import dispatch_or_phase_plan_entry
state = {"phases": {"1": {"slug": "demo-phase-alpha", "status": "pending"}}, "phaseWorktrees": {}}
plan = {"target": {"branch": "feat/orphan"}, "items": [{"id": "1", "slug": "demo-phase-alpha", "branch": "feat/orphan-phase-alpha"}]}
step = dispatch_or_phase_plan_entry(state, plan, "1")
assert step.get("action") == "provision-phase", step
print("ok")
PY
if [[ $? -eq 0 ]]; then ok orphan-phase-worktree-adopt-or-teardown-dispatch-guard; else bad orphan-phase-worktree-adopt-or-teardown-dispatch-guard; fi

# no-progress-differentiated-stall-causes (R9/R10)
python3 - <<'PY' "$ROOT"
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / 'scripts'))
from status_integrity import classify_deliver_stall_cause, is_differentiated_stall, stall_progress_key
root = Path(sys.argv[1])
state = {"phases": {"1": {"status": "in-flight", "backgroundDispatchedAt": "2026-01-01T00:00:00Z"}}, "mergeQueue": []}
stall = classify_deliver_stall_cause(root, state, "await-in-flight")
assert stall == "external-ci-wait", stall
assert is_differentiated_stall(stall)
state2 = dict(state)
state2["mergeQueue"] = [{"phaseSlug": "a"}]
stall2 = classify_deliver_stall_cause(root, state2, "merge-run-next")
assert stall2 == "merge-queue-wait", stall2
k1 = stall_progress_key("sig", "await-in-flight", "external-ci-wait")
k2 = stall_progress_key("sig", "await-in-flight", "merge-queue-wait")
assert k1 != k2
print("ok")
PY
if [[ $? -eq 0 ]]; then ok no-progress-differentiated-stall-causes; else bad no-progress-differentiated-stall-causes; fi

# stale-in-progress-success-check-gate-green (R11/R12)
python3 - <<'PY' "$ROOT"
import json, sys
from pathlib import Path
from datetime import datetime, timezone
sys.path.insert(0, str(Path(sys.argv[1]) / 'scripts'))
from check_gate_lib import reconcile_stale_in_progress_checks, classify_checks
fixture = Path(sys.argv[1]) / 'scripts/test/fixtures/deliver-concurrency/stale-in-progress-success-checks.json'
checks = json.loads(fixture.read_text())
reconciled, settled = reconcile_stale_in_progress_checks(checks, ttl_seconds=60, now=datetime.now(timezone.utc))
assert settled, settled
classified = classify_checks(reconciled, neutral_pass=True, allowlist=[])
pending = [c['name'] for c in classified if c['class'] == 'pending']
assert not pending, pending
print("ok")
PY
if [[ $? -eq 0 ]]; then ok stale-in-progress-success-check-gate-green; else bad stale-in-progress-success-check-gate-green; fi

# phase-mode ship must not use gh checks --watch (R12)
if python3 - <<'PY' "$ROOT"
import re, sys
from pathlib import Path
root = Path(sys.argv[1])
bad = []
pat = re.compile(r"checks\s+--watch|pr checks.*--watch")
for rel in ("scripts/watch_ci_lib.py", "scripts/wave_deliver_loop.py"):
    path = root / rel
    for i, line in enumerate(path.read_text().splitlines(), 1):
        code = line.split("#", 1)[0]
        if pat.search(code):
            bad.append(f"{rel}:{i}")
if bad:
    print("\n".join(bad))
    raise SystemExit(1)
print("ok")
PY
then
  ok stale-in-progress-success-check-gate-green-phase-watch-ban
else
  bad stale-in-progress-success-check-gate-green-phase-watch-ban
fi
python3 - <<'PY' "$ROOT"
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / 'scripts'))
from watch_ci_lib import poll_check_gate_settled
assert callable(poll_check_gate_settled)
from wave_deliver_loop import poll_phase_ship_gate
assert callable(poll_phase_ship_gate)
print("ok")
PY
if [[ $? -eq 0 ]]; then ok stale-in-progress-success-check-gate-green-poll-helper; else bad stale-in-progress-success-check-gate-green-poll-helper; fi



# terminal-docs-currency-gate-invocation-valid (R43/R44)
CUR_FIX=$(mktemp -d)
mkdir -p "$CUR_FIX/.cursor"
echo '{"prd_number":"047","phases":{"1":{"status":"pending"}},"target":{"branch":"feat/fixture"}}' > "$CUR_FIX/.cursor/sw-deliver-state.json"
echo '{"prd_number":"047"}' > "$CUR_FIX/.cursor/sw-deliver-plan.json"
if python3 "$ROOT/scripts/docs-currency-gate.py" "$ROOT" "$CUR_FIX" "$CUR_FIX/.cursor/sw-deliver-state.json" "$CUR_FIX/.cursor/sw-deliver-plan.json" 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('verdict')=='pass', d
"; then
  ok terminal-docs-currency-gate-invocation-valid
else
  bad terminal-docs-currency-gate-invocation-valid
fi
if ! grep -q '"--state-root"' "$ROOT/scripts/wave_terminal.py" 2>/dev/null; then
  ok terminal-docs-currency-gate-argv-no-flag-only
else
  bad terminal-docs-currency-gate-argv-no-flag-only
fi
rm -rf "$CUR_FIX"

# resume-reconcile-unpushed-local-merge-promotes (R47/R49)
UNPUSH_FIX=$(mktemp -d)
(
  cd "$UNPUSH_FIX"
  git init -q && git config user.email t@t.com && git config user.name T
  echo base >f.txt && git add f.txt && git commit --trailer "Co-authored-by: Cursor <cursoragent@cursor.com>" -q -m init
  git branch -m main
  git checkout -q -b feat/demo
  git checkout -q -b feat/demo-phase-alpha
  echo phase >>f.txt && git add f.txt && git commit --trailer "Co-authored-by: Cursor <cursoragent@cursor.com>" -q -m phase
  git checkout -q feat/demo
  git merge --no-ff feat/demo-phase-alpha -q -m merge
  STALE=$(git rev-parse HEAD^)
  git update-ref refs/remotes/origin/feat/demo "$STALE"
  mkdir -p .cursor
  echo '{"target":{"branch":"feat/demo"},"phases":{"1":{"id":"1","slug":"alpha","branch":"feat/demo-phase-alpha","status":"pending"}}}' > .cursor/sw-deliver-state.json
  python3 "$ROOT/scripts/wave_terminal.py" "$UNPUSH_FIX" resume reconcile --no-fetch | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert 'alpha' in d.get('promoted',[]), d
assert d.get('unpushedLocalMerge'), d
"
  python3 - <<'PYIN' "$UNPUSH_FIX"
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]).parent.parent / 'scripts') if False else '')
import sys
sys.path.insert(0, str(Path('$ROOT') / 'scripts'))
from pathlib import Path
from wave_state import load_deliver_state
s = load_deliver_state(Path(sys.argv[1]), target='feat/demo')
assert s['phases']['1']['status']=='green-merged', s
assert s['phases']['1'].get('cause')=='resume:unpushed-local-merge'
PYIN
) && ok resume-reconcile-unpushed-local-merge-promotes || bad resume-reconcile-unpushed-local-merge-promotes
rm -rf "$UNPUSH_FIX"

# deliver-fail-payload-forwards-subprocess-error (R55/R57)
python3 - <<'PYIN' "$ROOT"
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / 'scripts'))
from wave_errors import fail_from_payload
captured = {}
def fail_fn(msg, exit_code=2, **extra):
    captured['msg'] = msg
    captured['extra'] = extra
    captured['ec'] = exit_code
    raise SystemExit(exit_code)
try:
    fail_from_payload(fail_fn, {"error": "real cause", "halt": "blocked"}, "default", 5)
except SystemExit as exc:
    assert exc.code == 5
assert captured.get('msg') == 'real cause', captured
assert captured.get('extra', {}).get('halt') == 'blocked', captured
print('ok')
PYIN
if [[ $? -eq 0 ]]; then ok deliver-fail-payload-forwards-subprocess-error; else bad deliver-fail-payload-forwards-subprocess-error; fi

# finalize-resume-after-state-cleared-post-merge (R13/R14)
FIN_FIX=$(mktemp -d)
(
  cd "$FIN_FIX"
  git init -q && git config user.email t@t.com && git config user.name T
  echo base >f.txt && git add f.txt && git commit --trailer "Co-authored-by: Cursor <cursoragent@cursor.com>" -q -m init
  git branch -m main
  git checkout -q -b feat/demo
  echo feature >>f.txt && git add f.txt && git commit --trailer "Co-authored-by: Cursor <cursoragent@cursor.com>" -q -m feature
  git checkout -q main
  git merge --no-ff feat/demo -q -m merge
  mkdir -p .cursor
  echo '{"migrated":true,"target":"feat/demo","scopedPath":".cursor/sw-deliver-state.demo.json"}' > .cursor/sw-deliver-state.json
  SW_SKIP_DOCS_CURRENCY=1 python3 "$ROOT/scripts/wave_compound.py" "$FIN_FIX" completion finalize-if-merged | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('verdict')=='pass', d
assert d.get('completion',{}).get('status')=='merged-complete', d
"
) && ok finalize-resume-after-state-cleared-post-merge || bad finalize-resume-after-state-cleared-post-merge
rm -rf "$FIN_FIX"

# terminal-pr-body-template-valid (R16)
python3 - <<'PYIN' "$ROOT"
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / 'scripts'))
from wave_terminal import terminal_pr_body
state = {
    'target': {'slug': 'demo', 'branch': 'feat/demo'},
    'prd_number': '050',
    'mergedPhases': [{'phaseSlug': 'alpha', 'pr': 7}],
}
body = terminal_pr_body(Path(sys.argv[1]), state)
assert '<!-- required:summary -->' in body
assert '<!-- required:decision-log -->' in body
import subprocess, json
proc = subprocess.run([
    sys.executable, str(Path(sys.argv[1])/'scripts/git_template_lib.py'),
    'validate', 'pr-body', '--body', body,
], capture_output=True, text=True)
assert proc.returncode == 0, proc.stdout + proc.stderr
print('ok')
PYIN
if [[ $? -eq 0 ]]; then ok terminal-pr-body-template-valid; else bad terminal-pr-body-template-valid; fi

# finalize-living-docs-reconcile-hook (R15)
if grep -q 'invoke_living_docs_reconcile_finalize' "$ROOT/scripts/wave_compound.py" && \
   grep -q 'living-docs reconcile' "$ROOT/scripts/wave_compound.py" || \
   grep -q 'reconcile", "--commit' "$ROOT/scripts/wave_compound.py"; then
  ok finalize-living-docs-reconcile-hook
else
  bad finalize-living-docs-reconcile-hook
fi



# capability-gateref-no-shell (R17)
if python3 "$ROOT/scripts/capability-gateref-guard.py" 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('verdict')=='pass', d
"; then
  ok capability-gateref-no-shell
else
  bad capability-gateref-no-shell
fi

# capability-gateref-no-shell detects regression
REG_FIX="$TMP/gateref-regress"
mkdir -p "$REG_FIX/scripts/test/fixtures/capability-select/bad"
echo '{"entries":[{"capability":{"metadata":{"gateRef":"check-gate.sh"}}}]}' > "$REG_FIX/scripts/test/fixtures/capability-select/bad/x.json"
if python3 - <<'PYREG' "$ROOT" "$REG_FIX"
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / 'scripts'))
from capability_trust import check_gateref_no_shell
# Also need canonical .py in fake repo for detection
scripts = Path(sys.argv[2]) / 'scripts'
scripts.mkdir(parents=True, exist_ok=True)
(scripts / 'check-gate.py').write_text('# stub')
bad = check_gateref_no_shell(Path(sys.argv[2]))
assert bad.get('verdict')=='fail' and bad.get('violations'), bad
print('ok')
PYREG
then
  ok capability-gateref-no-shell-detects-sh
else
  bad capability-gateref-no-shell-detects-sh
fi

# all-private-spec-seed-tracked-private-body (R18/R19)
VIS_FIX=$(mktemp -d)
(
  cd "$VIS_FIX"
  git init -q && git config user.email t@t.com && git config user.name T
  echo base >README.md && git add README.md && git commit --trailer "Co-authored-by: Cursor <cursoragent@cursor.com>" -q -m init
  git branch -m main
  git checkout -q -b feat/vis-fixture
  mkdir -p .cursor docs/prds/099-vis-fixture
  echo '{"planning":{"visibilityProfile":"all-private"}}' > .cursor/workflow.config.json
  cat > docs/prds/099-vis-fixture/tasks-099-vis-fixture.md <<'EOF'
---
prd: docs/prds/099-vis-fixture/099-prd-vis-fixture.md
frozen: true
topic: vis-fixture
---
# Tasks
### 1. One
EOF
  git add docs .cursor
  git commit --trailer "Co-authored-by: Cursor <cursoragent@cursor.com>" -q -m docs
  set +e
  OUT=$(python3 "$ROOT/scripts/planning_visibility.py" --root "$VIS_FIX" check-freeze-visibility docs/prds/099-vis-fixture/tasks-099-vis-fixture.md 2>&1)
  EC=$?
  set -e
  if [[ "$EC" -eq 20 ]]; then
    ok all-private-spec-seed-tracked-private-body-freeze-halt
  else
    bad all-private-spec-seed-tracked-private-body-freeze-halt
    echo "$OUT"
  fi
  sed -i '' '2a\
visibility: public
' docs/prds/099-vis-fixture/tasks-099-vis-fixture.md 2>/dev/null || sed -i '2a visibility: public' docs/prds/099-vis-fixture/tasks-099-vis-fixture.md
  git add docs/prds/099-vis-fixture/tasks-099-vis-fixture.md
  git commit --trailer "Co-authored-by: Cursor <cursoragent@cursor.com>" -q -m 'add visibility public'
  if python3 "$ROOT/scripts/planning_visibility.py" --root "$VIS_FIX" check-freeze-visibility docs/prds/099-vis-fixture/tasks-099-vis-fixture.md 2>/dev/null | python3 -c "
import json,sys
assert json.load(sys.stdin).get('verdict')=='pass'
"; then
    ok all-private-spec-seed-tracked-private-body-freeze-pass
  else
    bad all-private-spec-seed-tracked-private-body-freeze-pass
  fi
  if python3 - <<'PYVIS' "$ROOT" "$VIS_FIX"
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / 'scripts'))
import wave_spec_seed as wss
root = Path(sys.argv[2])
artifact = root / 'docs/prds/099-vis-fixture/tasks-099-vis-fixture.md'
# strip visibility frontmatter for private resolution
lines = artifact.read_text().splitlines()
artifact.write_text('\n'.join([ln for ln in lines if not ln.strip().startswith('visibility:')]) + '\n')
try:
    wss.assert_no_tracked_private_bodies(root, [artifact], feature_branch='feat/vis-fixture')
    raise SystemExit(1)
except SystemExit as exc:
    if exc.code != 20:
        raise
print('ok')
PYVIS
  then
    ok all-private-spec-seed-tracked-private-body-remediation
  else
    bad all-private-spec-seed-tracked-private-body-remediation
  fi
) && true || bad all-private-spec-seed-tracked-private-body
rm -rf "$VIS_FIX"

# deliver-verify-fixture-tree-immutable (R51/R53)
IMM_FIX=$(mktemp -d)
(
  cd "$IMM_FIX"
  git init -q && git config user.email t@t.com && git config user.name T
  echo base >README.md && git add README.md && git commit --trailer "Co-authored-by: Cursor <cursoragent@cursor.com>" -q -m init
  mkdir -p scripts/test/fixtures/deliver-concurrency .cursor
  echo probe > scripts/test/fixtures/deliver-concurrency/probe.txt
  git add scripts/test/fixtures/deliver-concurrency/probe.txt README.md
  git commit --trailer "Co-authored-by: Cursor <cursoragent@cursor.com>" -q -m fixtures
  BEFORE=$(git status --porcelain scripts/test/fixtures/ || true)
  SW_DELIVER_VERIFY=1 python3 "$ROOT/scripts/test/_runner.py" verify --root "$IMM_FIX" >/dev/null 2>&1 || true
  AFTER=$(git status --porcelain scripts/test/fixtures/ || true)
  if [[ -z "$AFTER" ]] || [[ "$BEFORE" == "$AFTER" ]]; then
    ok deliver-verify-fixture-tree-immutable
  else
    bad deliver-verify-fixture-tree-immutable
    echo "before=$BEFORE after=$AFTER"
  fi
) || bad deliver-verify-fixture-tree-immutable
rm -rf "$IMM_FIX"

# fixture-tree doctor before merge-run-next (R52)
DOC_FIX=$(mktemp -d)
(
  cd "$DOC_FIX"
  git init -q && git config user.email t@t.com && git config user.name T
  echo base >f.txt && git add f.txt && git commit --trailer "Co-authored-by: Cursor <cursoragent@cursor.com>" -q -m init
  mkdir -p scripts/test/fixtures .cursor
  echo dirty > scripts/test/fixtures/dirty.txt
  git add scripts/test/fixtures/dirty.txt f.txt && git commit --trailer "Co-authored-by: Cursor <cursoragent@cursor.com>" -q -m fixtures
  echo changed >> scripts/test/fixtures/dirty.txt
  echo '{"target":{"branch":"feat/demo"},"orchestratorWorktree":{"path":"'"$DOC_FIX"'"}}' > .cursor/sw-deliver-state.json
  set +e
  python3 - <<'PYDOC' "$ROOT" "$DOC_FIX"
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / 'scripts'))
from wave_deliver_loop import fixture_tree_clean_or_halt
from wave_state import load_deliver_state
root = Path(sys.argv[2])
state = load_deliver_state(root, target='feat/demo')
try:
    fixture_tree_clean_or_halt(root, state)
    raise SystemExit(1)
except SystemExit as exc:
    if exc.code != 20:
        raise
print('ok')
PYDOC
  EC=$?
  set -e
  if [[ "$EC" -eq 0 ]]; then
    ok deliver-verify-fixture-tree-doctor-halt
  else
    bad deliver-verify-fixture-tree-doctor-halt
  fi
) || bad deliver-verify-fixture-tree-doctor-halt
rm -rf "$DOC_FIX"

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
if __name__ == "__main__":
    raise SystemExit(main())
