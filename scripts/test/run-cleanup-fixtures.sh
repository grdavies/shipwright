#!/usr/bin/env bash
# Fixtures for /sw-cleanup (PRD 007 Phase 10 — R28–R34, R56).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CLEANUP="$ROOT/scripts/cleanup.sh"
CLEANUP_PY="$ROOT/scripts/cleanup_lib.py"
FAIL=0

ok()   { echo "OK  $1"; }
bad()  { echo "FAIL $1"; FAIL=1; }

# --- cleanup-dry-run-default ---
FIX=$(mktemp -d)
trap 'rm -rf "$FIX"' EXIT
cd "$FIX"
git init -q
git config user.email test@test.com
git config user.name Test
git commit --allow-empty -q -m init
git branch -M main
git checkout -q -b feat/merged-demo
git commit --allow-empty -q -m feat
git checkout -q main
git merge --no-ff feat/merged-demo -q -m merge
if OUT=$(bash "$CLEANUP" 2>/dev/null) && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
r=d['report']
assert r['dryRun'] is True
assert any(i['kind']=='branch' and i['name']=='feat/merged-demo' for i in r['wouldRemove'])
assert any(i['reason']=='protected' for i in r['protected'] if i['kind']=='branch' and i['name']=='main')
"; then
  ok "cleanup-dry-run-default: dry-run lists merged branch + protects main"
else
  bad "cleanup-dry-run-default"
fi

# confirm gate without --yes refuses
set +e
bash "$CLEANUP" --confirm 2>/dev/null
EC=$?
set -e
if [[ "$EC" -eq 2 ]]; then
  ok "cleanup-dry-run-default: confirm requires --yes"
else
  bad "cleanup-dry-run-default: confirm gate ec=$EC"
fi

# --- cleanup-protects-inflight ---
mkdir -p .cursor
echo '{"verdict":"running","mergeJournal":{"phase":"alpha"}}' >.cursor/sw-deliver-state.json
echo '{"target":"feat/x"}' >.cursor/sw-deliver.lock
if bash "$CLEANUP" 2>/dev/null | python3 -c "
import json,sys
r=json.load(sys.stdin)['report']
assert any(i['kind']=='run-state' and i['reason']=='protected' for i in r['protected'])
"; then
  ok "cleanup-protects-inflight: in-flight deliver state protected"
else
  bad "cleanup-protects-inflight: in-flight state"
fi

# --- cleanup-orchestrator-state-root ---
ORCH_FIX=$(mktemp -d)
cd "$ORCH_FIX"
git init -q
git config user.email test@test.com
git config user.name Test
git commit --allow-empty -q -m init
git branch -M main
git checkout -q -b feat/orch-demo
git commit --allow-empty -q -m feat
ORCH_WT="$ORCH_FIX/.sw-worktrees/orch-demo-orchestrator"
mkdir -p "$(dirname "$ORCH_WT")"
git checkout -q main
git worktree add -q "$ORCH_WT" feat/orch-demo
git merge --no-ff feat/orch-demo -q -m merge
mkdir -p .cursor "$ORCH_WT/.cursor"
cat >.cursor/sw-deliver-state.json <<JSON
{"verdict":"running","updatedAt":"2026-01-01T00:00:00Z","orchestratorWorktree":{"path":"$ORCH_WT"}}
JSON
cat >"$ORCH_WT/.cursor/sw-deliver-state.json" <<'JSON'
{"verdict":"complete","updatedAt":"2026-06-25T22:00:00Z","orchestratorWorktree":{"path":"ORCH_PLACEHOLDER"}}
JSON
python3 -c "
import json
from pathlib import Path
p=Path('$ORCH_WT/.cursor/sw-deliver-state.json')
s=json.loads(p.read_text())
s['orchestratorWorktree']['path']='$ORCH_WT'
p.write_text(json.dumps(s))
"
if python3 "$CLEANUP_PY" "$ORCH_FIX" 2>/dev/null | python3 -c "
import json,sys
r=json.load(sys.stdin)['report']
prot=[i for i in r['protected'] if i['kind']=='worktree' and 'orch-demo-orchestrator' in i['name']]
assert not prot, prot
assert any(i['kind']=='worktree' and 'orch-demo-orchestrator' in i['name'] for i in r['wouldRemove'])
assert any(i['kind']=='run-state' and i['name']=='.cursor/sw-deliver-state.json' and i['reason']=='stale-copy' for i in r['wouldRemove'])
assert not any(i['kind']=='run-state' and i['reason']=='protected' for i in r['protected'])
"; then
  ok "cleanup-orchestrator-state-root: stale root running does not block terminal orch state"
else
  bad "cleanup-orchestrator-state-root"
fi
rm -rf "$ORCH_FIX"
cd "$FIX"

if ! grep -q 'rm -rf' "$ROOT/scripts/cleanup_lib.py" && \
   ! grep -qE '^\s*rm\s' "$ROOT/scripts/cleanup.sh"; then
  ok "cleanup-protects-inflight: no rm -rf invocation in cleanup scripts"
else
  bad "cleanup-protects-inflight: rm -rf invocation present"
fi

if grep -q '"worktree", "remove"' "$ROOT/scripts/cleanup_lib.py" && \
   grep -q 'worktree remove' "$ROOT/core/commands/sw-cleanup.md"; then
  ok "cleanup-protects-inflight: worktree remove documented"
else
  bad "cleanup-protects-inflight: worktree remove"
fi

# --- cleanup-squash-merge-aware ---
SQ=$(mktemp -d)
cd "$SQ"
git init -q
git config user.email test@test.com
git config user.name Test
git commit --allow-empty -q -m init
git branch -M main
git checkout -q -b feat/squash-only
echo squash-content >squash.txt && git add squash.txt && git commit -q -m only-on-branch
git checkout -q main
git merge --squash feat/squash-only -q
git commit -q -m 'squash feat'
if python3 "$CLEANUP_PY" "$SQ" 2>/dev/null | python3 -c "
import json,sys
r=json.load(sys.stdin)['report']
names=[i['name'] for i in r['wouldRemove'] if i['kind']=='branch']
assert 'feat/squash-only' in names
"; then
  ok "cleanup-squash-merge-aware: squash-merged branch detected"
else
  bad "cleanup-squash-merge-aware: squash merged"
fi
git checkout -q -b feat/indeterminate
echo unique >only.txt && git add only.txt && git commit -q -m unique
git checkout -q main
if python3 "$CLEANUP_PY" "$SQ" 2>/dev/null | python3 -c "
import json,sys
r=json.load(sys.stdin)['report']
prot=[i for i in r['protected'] if i['name']=='feat/indeterminate']
assert prot and prot[0]['reason'] in ('unmerged','indeterminate')
"; then
  ok "cleanup-squash-merge-aware: unmerged branch protected"
else
  bad "cleanup-squash-merge-aware: unmerged protected"
fi
rm -rf "$SQ"
cd "$FIX"

# --- cleanup-registered ---
CMD="$ROOT/core/commands/sw-cleanup.md"
if [[ -f "$CMD" ]] && grep -qE '^description:.*dry-run' "$CMD" && \
   grep -q 'Does not' "$CMD" && grep -q 'sw-cleanup' "$CMD"; then
  ok "cleanup-registered: sw-cleanup command + description contract"
else
  bad "cleanup-registered"
fi
if [[ -x "$ROOT/scripts/cleanup.sh" ]]; then
  ok "cleanup-registered: cleanup.sh executable"
else
  bad "cleanup-registered: cleanup.sh executable"
fi

# --- cleanup-autonomy (PRD 013 A1 R25/R26) ---
AUTO_FIX=$(mktemp -d)
(
  cd "$AUTO_FIX"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  git commit --allow-empty -q -m init
  git branch -M main
  git checkout -q -b feat/merged-auto
  git commit --allow-empty -q -m feat
  git checkout -q main
  git merge --no-ff feat/merged-auto -q -m merge
  mkdir -p .cursor
  cat >.cursor/workflow.config.json <<'JSON'
{"defaultBaseBranch":"main","cleanup":{"autonomy":"auto"}}
JSON
  if OUT=$(python3 "$CLEANUP_PY" "$AUTO_FIX" --autonomous 2>/dev/null) && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('verdict')=='pass'
assert d.get('action')=='cleanup-autonomous-apply'
removed=[i['name'] for i in d['report'].get('removed',[]) if i.get('kind')=='branch']
assert 'feat/merged-auto' in removed
"; then
    ok "cleanup-autonomy-auto-after-merge"
  else
    bad "cleanup-autonomy-auto-after-merge"
  fi
) || bad "cleanup-autonomy-auto-after-merge"

if python3 -c "
import sys
sys.path.insert(0, '$ROOT/scripts')
from pathlib import Path
from cleanup_lib import Report, Item, can_autonomous_apply, cleanup_autonomy_mode
root = Path('$ROOT')
report = Report(dry_run=True, protected=[Item('branch', 'feat/x', 'indeterminate', 'squash')])
# config default is confirm — override check by testing reason path directly
assert can_autonomous_apply(root, report)[0] is False or cleanup_autonomy_mode(root) != 'auto'
report2 = Report(dry_run=True, protected=[Item('branch', 'feat/x', 'indeterminate', 'squash')])
# simulate auto: monkeypatch via temp config
import json, tempfile, os
td = tempfile.mkdtemp()
cfg = root / '.cursor' / 'workflow.config.json'
data = json.loads(cfg.read_text())
data.setdefault('cleanup', {})['autonomy'] = 'auto'
(tmp := Path(td) / '.cursor').mkdir(parents=True)
(tmp / 'workflow.config.json').write_text(json.dumps(data))
assert can_autonomous_apply(Path(td), report2) == (False, 'indeterminate merge status — human gate required')
"; then
  ok "cleanup-autonomy-indeterminate-falls-back"
else
  bad "cleanup-autonomy-indeterminate-falls-back"
fi

if [[ "$FAIL" -ne 0 ]]; then
  echo "cleanup fixtures: FAIL"
  exit 1
fi
echo "cleanup fixtures: PASS"
