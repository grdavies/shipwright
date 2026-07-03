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
# Fixtures for branch-name conformance (PRD 007 Phase 1 — R22/R23/R24/R25/R26/R27).
# Scenarios: branch-name-guard-floor, branch-name-guard-creation,
# branch-name-guard-multifeature, pf-matcher-migration.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GUARD="$ROOT/scripts/branch-name-guard.sh"
FAIL=0

ok()   { echo "OK  $1"; }
bad()  { echo "FAIL $1"; FAIL=1; }

# --- branch-name-guard-creation: conforming names pass ---
if bash "$GUARD" validate feat/foo >/dev/null 2>&1 \
   && bash "$GUARD" validate fix/bar-baz >/dev/null 2>&1 \
   && bash "$GUARD" validate chore/deliver-autonomy-hardening-phase-x >/dev/null 2>&1; then
  ok "branch-name-guard-creation: conforming names accepted"
else
  bad "branch-name-guard-creation: conforming names accepted"
fi

# --- branch-name-guard-creation: pf/ and bare names rejected ---
if ! bash "$GUARD" validate pf/006-caveman >/dev/null 2>&1 \
   && ! bash "$GUARD" validate random-branch >/dev/null 2>&1 \
   && ! bash "$GUARD" validate bogus/thing >/dev/null 2>&1; then
  ok "branch-name-guard-creation: non-conforming (incl. pf/) rejected"
else
  bad "branch-name-guard-creation: non-conforming (incl. pf/) rejected"
fi

# --- branch-name-guard-floor: worktree.py has no pf/ default; calls the guard ---
if ! grep -qE ':-pf/' "$ROOT/scripts/worktree.py" \
   && grep -qE 'branch-name-guard.py' "$ROOT/scripts/worktree.py"; then
  ok "branch-name-guard-floor: worktree.py floor fixed + guarded"
else
  bad "branch-name-guard-floor: worktree.py floor fixed + guarded"
fi

# --- types single-sourced from release-please-config.json ---
CFG_TYPES="$(python3 -c "import json;d=json.load(open('$ROOT/release-please-config.json'));print(' '.join(sorted({s['type'] for p in d['packages'].values() for s in p['changelog-sections'] if s.get('type')})))")"
GUARD_TYPES="$(bash "$GUARD" types | tr ' ' '\n' | sort | tr '\n' ' ' | sed 's/ $//')"
if [[ "$CFG_TYPES" == "$GUARD_TYPES" ]]; then
  ok "branch-name-guard: types single-sourced from release-please-config.json"
else
  bad "branch-name-guard: types single-sourced (cfg='$CFG_TYPES' guard='$GUARD_TYPES')"
fi

# --- branch-name-guard-multifeature: wave_deliver.py emits conforming branches ---
MF_BRANCH="$(python3 -c "
import importlib.util
spec=importlib.util.spec_from_file_location('wd','$ROOT/scripts/wave_deliver.py')
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(sorted(m.VALID_TYPES)==['chore','docs','feat','fix','perf','refactor','revert','test'])
")"
if [[ "$MF_BRANCH" == "True" ]] && ! grep -qE 'f"pf/\{i\}"' "$ROOT/scripts/wave_deliver.py"; then
  ok "branch-name-guard-multifeature: wave_deliver derivation conforming"
else
  bad "branch-name-guard-multifeature: wave_deliver derivation conforming"
fi

# --- pf-matcher-migration: no pf/ matchers in reconcile/impl fixtures ---
if ! grep -qE '\^pf/' "$ROOT/scripts/reconcile.py" \
   && ! grep -qE 'pf/' "$ROOT/scripts/unit_tests/w4/harness_impl.py"; then
  ok "pf-matcher-migration: reconcile + impl fixtures migrated off pf/"
else
  bad "pf-matcher-migration: reconcile + impl fixtures migrated off pf/"
fi

if [[ "$FAIL" -ne 0 ]]; then
  echo "branch-guard fixtures: FAIL"
  exit 1
fi
echo "branch-guard fixtures: PASS"

"""

if __name__ == "__main__":
    raise SystemExit(main())
