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
# Fixtures for pre-merge compounding + completion semantics (PRD 007 Phase 8).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WC="$ROOT/scripts/wave_compound.py"
LOOP="$ROOT/scripts/wave_deliver_loop.py"
COMPOUND_SHIP="$ROOT/core/commands/sw-compound-ship.md"
RETROSPECTIVE="$ROOT/core/commands/sw-retrospective.md"
FAIL=0

ok()  { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

FIX=$(mktemp -d)
trap 'rm -rf "$FIX"' EXIT

cd "$FIX"
git init -q
git config user.email test@test.com
git config user.name Test
mkdir -p docs/prds .cursor
cat >.cursor/sw-base-state.json <<'JSON'
{"trunkBase": {"name": "main", "sha": "deadbeef00000000000000000000000000000000"}}
JSON
echo '| Date | PRD | Phase | Notes |' > docs/prds/COMPLETION-LOG.md
echo '|---|---|---|---|' >> docs/prds/COMPLETION-LOG.md
echo '_No entries yet._' >> docs/prds/COMPLETION-LOG.md
echo '| # | Slug | PRD | Tasks | Status |' > docs/prds/INDEX.md
echo '|---|---|---|---|---|' >> docs/prds/INDEX.md
echo '| 007 | deliver-autonomy | link | link | not-started |' >> docs/prds/INDEX.md
git add docs/prds && git commit -q -m init
git branch -m feat/demo

cat >.cursor/sw-deliver-plan.json <<'JSON'
{"mode":"phase","target":{"branch":"feat/demo"},"items":[{"id":"1","slug":"alpha","branch":"feat/demo-phase-alpha"}]}
JSON

cat >.cursor/sw-deliver-state.json <<JSON
{
  "verdict": "running",
  "target": {"branch": "feat/demo"},
  "phases": {"1": {"slug": "alpha", "status": "green-merged", "branch": "feat/demo-phase-alpha"}},
  "orchestratorWorktree": {"path": "$FIX"},
  "compoundShip": {},
  "completion": {}
}
JSON

# --- compound-ship-premerge-commit ---
if OUT=$(python3 "$WC" "$FIX" compound-ship premerge-env 2>/dev/null) && \
   echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['invoke']=='/sw-compound-ship --pre-merge'
assert d['memoryCommit'] is False
assert d['fileOutputsCommit'] is True
"; then
  ok "compound-ship-premerge-commit: premerge-env contract"
else
  bad "compound-ship-premerge-commit: premerge-env contract"
fi

if python3 "$WC" "$FIX" compound-ship record-premerge --prd 007 --phase deliver --notes "test" >/dev/null 2>&1 && \
   python3 -c "
import json, sys
sys.path.insert(0, '$ROOT/scripts')
from pathlib import Path
from wave_state import load_deliver_state
s = load_deliver_state(Path('.'), target='feat/demo')
assert s['compoundShip']['premergeDone'] is True
assert s['completion']['status']=='completed-pending-merge'
"; then
  ok "compound-ship-premerge-commit: record-premerge sets pending state"
else
  bad "compound-ship-premerge-commit: record-premerge sets pending state"
fi

echo log >> docs/prds/COMPLETION-LOG.md
git add docs/prds/COMPLETION-LOG.md && git commit -q -m "completion log"
if python3 "$WC" "$FIX" compound-ship check-file-outputs --base HEAD~1..HEAD >/dev/null 2>&1; then
  ok "compound-ship-premerge-commit: allowed file outputs pass check"
else
  bad "compound-ship-premerge-commit: allowed file outputs pass check"
fi

mkdir -p .cursor/memory
echo secret > .cursor/memory/leak.txt
git add .cursor/memory/leak.txt
git commit -q -m "bad memory"
EC_MEM=0
python3 "$WC" "$FIX" compound-ship check-file-outputs --base HEAD~1..HEAD >/dev/null 2>&1 || EC_MEM=$?
git reset -q --hard HEAD~1
if [[ "$EC_MEM" -ne 0 ]]; then
  ok "compound-ship-premerge-commit: memory-like paths rejected"
else
  bad "compound-ship-premerge-commit: memory-like paths rejected"
fi

# --- compound-ship-rule-class-gated ---
if grep -q 'human-gated' "$RETROSPECTIVE" && grep -q 'Never auto-promote rule-class' "$RETROSPECTIVE"; then
  ok "compound-ship-rule-class-gated: rule-class promotion human-gated in command"
else
  bad "compound-ship-rule-class-gated: rule-class promotion human-gated in command"
fi

# --- completion-pending-merge-decline ---
if OUT=$(python3 "$WC" "$FIX" completion status 2>/dev/null) && \
   echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['completion']['status']=='completed-pending-merge'
assert d['reportsComplete'] is False
assert d['mergeDetected'] is False
"; then
  ok "completion-pending-merge-decline: pending merge does not report complete"
else
  bad "completion-pending-merge-decline: pending merge does not report complete"
fi

if OUT=$(python3 "$LOOP" "$FIX" compute-next 2>/dev/null) && \
   echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['next']['action']=='terminal-ship'
"; then
  ok "completion-pending-merge-decline: deliver-loop awaits merge not complete"
else
  bad "completion-pending-merge-decline: deliver-loop awaits merge not complete"
fi

# --- deliver-suggest-cleanup-on-merge ---
git branch -m main
git checkout -q -b feat/demo
echo feature >> docs/prds/COMPLETION-LOG.md
git add docs/prds/COMPLETION-LOG.md && git commit -q -m feature
git checkout -q main
git merge -q --no-ff feat/demo -m "merge feature"
git checkout -q feat/demo

if OUT=$(python3 "$WC" "$FIX" completion check-merge 2>/dev/null) && \
   echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['merged'] is True, d
"; then
  ok "deliver-suggest-cleanup-on-merge: merge detected on target branch"
else
  bad "deliver-suggest-cleanup-on-merge: merge detected on target branch"
fi

if OUT=$(python3 "$LOOP" "$FIX" compute-next 2>/dev/null) && \
   echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['next']['action']=='finalize-completion'
"; then
  ok "deliver-suggest-cleanup-on-merge: loop routes to finalize-completion"
else
  bad "deliver-suggest-cleanup-on-merge: loop routes to finalize-completion"
fi

if OUT=$(python3 "$WC" "$FIX" completion finalize-if-merged 2>/dev/null) && \
   echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert 'sw-cleanup' in d.get('cleanupSuggestion','').lower()
"; then
  ok "deliver-suggest-cleanup-on-merge: finalize suggests cleanup"
else
  bad "deliver-suggest-cleanup-on-merge: finalize suggests cleanup"
fi

# reconcile --require-merge does not flip INDEX without integration merge
MERGE_FIX=$(mktemp -d)
(
  cd "$MERGE_FIX"
  git init -q
  git config user.email t@t.com
  git config user.name T
  mkdir -p docs/prds
  printf '%s\n' '| # | Slug | PRD | Tasks | Status |' '|---|---|---|---|---|' '| 007 | x | l | l | not-started |' > docs/prds/INDEX.md
  git add docs/prds/INDEX.md && git commit -q -m init
  git checkout -q -b feat/demo2
  bash "$ROOT/scripts/reconcile.py" reconcile --require-merge >/dev/null 2>&1
  if grep -q '| complete |' docs/prds/INDEX.md; then
    exit 1
  fi
) && ok "compound-ship-premerge-commit: reconcile --require-merge holds INDEX" || bad "compound-ship-premerge-commit: reconcile --require-merge holds INDEX"

if [[ "$FAIL" -eq 0 ]]; then
  echo "compound-completion fixtures: all passed"
  exit 0
fi
echo "compound-completion fixtures: $FAIL failure(s)"
exit 1

"""

if __name__ == "__main__":
    raise SystemExit(main())
