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
# Fixtures for task-document currency (PRD 007 Phase 7 — R13–R16, R48–R49).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROGRESS="$ROOT/scripts/tasks-progress.sh"
GATE="$ROOT/scripts/tasks-currency-gate.sh"
CHECK_FROZEN="$ROOT/scripts/check-frozen.sh"
STATE_PY="$ROOT/scripts/wave_state.py"
FAIL=0

ok()  { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

FIX=$(mktemp -d)
trap 'rm -rf "$FIX"' EXIT

cd "$FIX"
git init -q
git config user.email test@test.com
git config user.name Test
mkdir -p docs/prds/099-test

cat > docs/prds/099-test/tasks-099-test.md <<'EOF'
---
frozen: true
---
# Tasks

- [ ] 1.1 First task
  - **File:** `a.sh`
- [ ] 2.1 Second task
  - **File:** `b.sh`
EOF

git add docs/prds/099-test/tasks-099-test.md
git commit -q -m "add frozen tasks"
mkdir -p .cursor

TASKS=docs/prds/099-test/tasks-099-test.md
PHASE=alpha

# --- tasks-checkbox-currency (R23: ledger records progress; frozen body unchanged) ---
echo '{"verdict":"running","source_task_list":"docs/prds/099-test/tasks-099-test.md","phases":{},"taskLedger":{"tasks":{},"phases":{}}}' \
  > .cursor/sw-deliver-state.json
TOGGLE_OUT=$(bash "$PROGRESS" toggle --file "$TASKS" --ref 1.1 --done true --phase "$PHASE" 2>/dev/null || true)
if echo "$TOGGLE_OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('action')=='ledger-toggle' and d.get('verdict')=='pass'" && \
   grep -q '\[ \] 1.1' "$TASKS" && \
   echo "$TOGGLE_OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert '- [x] 1.1' in d.get('projected','')"; then
  ok "tasks-checkbox-currency: ledger toggle projects done without mutating frozen body"
else
  bad "tasks-checkbox-currency: ledger toggle projects done without mutating frozen body"
fi

# --- tasks-progress-nonckbox-reject ---
cp docs/prds/099-test/tasks-099-test.md /tmp/tasks-before.md
if bash "$PROGRESS" check-diff --old /tmp/tasks-before.md --new "$TASKS" >/dev/null 2>&1; then
  : # checkbox-only ok
else
  bad "tasks-progress-nonckbox-reject: setup"
fi
echo "tampered" >> "$TASKS"
if bash "$PROGRESS" check-diff --old /tmp/tasks-before.md --new "$TASKS" >/dev/null 2>&1; then
  bad "tasks-progress-nonckbox-reject: non-checkbox edit should fail"
else
  ok "tasks-progress-nonckbox-reject: non-checkbox edit rejected"
fi
git checkout -q -- "$TASKS" 2>/dev/null || cp /tmp/tasks-before.md "$TASKS"

# --- frozen-guard-allows-checkbox (R23: progress does not rewrite hashed body) ---
if bash "$CHECK_FROZEN" HEAD >/dev/null 2>&1; then
  ok "frozen-guard-allows-checkbox: ledger progress leaves frozen body unchanged for check-frozen"
else
  bad "frozen-guard-allows-checkbox: ledger progress leaves frozen body unchanged for check-frozen"
fi

# Tampered frozen file should still fail
echo "# bad" >> "$TASKS"
git add "$TASKS"
git commit -q -m "tamper" 2>/dev/null || true
set +e
bash "$CHECK_FROZEN" HEAD~1 >/dev/null 2>&1
EC_TAMPER=$?
set -e
git reset -q --hard HEAD~1 2>/dev/null || true
if [[ "$EC_TAMPER" -eq 1 ]]; then
  ok "frozen-guard-allows-checkbox: non-checkbox frozen edit rejected"
else
  bad "frozen-guard-allows-checkbox: non-checkbox frozen edit rejected (ec=$EC_TAMPER)"
fi

# --- ledger + currency gate (R23: frozen checkboxes read from ledger) ---
echo '{"verdict":"running","source_task_list":"docs/prds/099-test/tasks-099-test.md","phases":{},"taskLedger":{"tasks":{},"phases":{}}}' \
  > .cursor/sw-deliver-state.json

if bash "$GATE" --tasks-file "$TASKS" --state-root "$FIX" >/dev/null 2>&1; then
  ok "tasks-currency-gate-block: unchecked ledger and body aligned passes"
else
  bad "tasks-currency-gate-block: unchecked ledger and body aligned should pass"
fi

python3 "$STATE_PY" "$FIX" ledger record --task 1.1 --phase "$PHASE" --done true >/dev/null
if bash "$GATE" --tasks-file "$TASKS" --state-root "$FIX" >/dev/null 2>&1; then
  ok "tasks-currency-gate-block: ledger aligned passes gate"
else
  bad "tasks-currency-gate-block: ledger aligned should pass"
fi

# wave.sh tasks-currency routing
if bash "$ROOT/scripts/wave.sh" tasks-currency --tasks-file "$TASKS" --state-root "$FIX" >/dev/null 2>&1; then
  ok "tasks-checkbox-currency: wave.sh tasks-currency routes to gate"
else
  bad "tasks-checkbox-currency: wave.sh tasks-currency routes to gate"
fi

# --- currency-gate-vs-ledger (R49): partial phase tolerated ---
echo '{"verdict":"running","source_task_list":"docs/prds/099-test/tasks-099-test.md","phases":{},"taskLedger":{"tasks":{"1.1":{"done":true,"phase":"alpha"}},"phases":{}}}' \
  > .cursor/sw-deliver-state.json
if bash "$GATE" --tasks-file "$TASKS" --state-root "$FIX" >/dev/null 2>&1; then
  ok "currency-gate-vs-ledger: ledger aligned with unchecked frozen body passes"
else
  bad "currency-gate-vs-ledger: ledger aligned with unchecked frozen body should pass"
fi

if [[ "$FAIL" -eq 0 ]]; then
  echo "tasks-currency fixtures: all passed"
  exit 0
fi
echo "tasks-currency fixtures: $FAIL failure(s)"
exit 1

"""

if __name__ == "__main__":
    raise SystemExit(main())
