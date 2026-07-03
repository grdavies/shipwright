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
# PRD 036 Phase 5 — deliver invariant regression guard (R22).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FAIL=0

ok()  { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

SW_DELIVER="$ROOT/core/commands/sw-deliver.md"
SCAN="$ROOT/scripts/secret-scan.py"
PUSH="$ROOT/scripts/git-push.py"
LOCK_PY="$ROOT/scripts/wave_lock.py"
FROZEN="$ROOT/scripts/check-frozen.py"
MANIFEST="$ROOT/core/sw-reference/pr-test-plan.manifest.json"

if grep -qE 'does not bypass.*main|auto-merge to `main`|human merge gate' "$SW_DELIVER" && \
   grep -q 'halts at the human merge gate' "$SW_DELIVER"; then
  ok "human-merge-gate-unchanged"
else
  bad "human-merge-gate-unchanged"
fi

if [[ -f "$SCAN" ]] && [[ -f "$PUSH" ]] && grep -q 'secret-scan' "$PUSH"; then
  ok "secret-scan-push-chokepoint"
else
  bad "secret-scan-push-chokepoint"
fi

if grep -q 'sw-deliver-locks' "$LOCK_PY" && grep -q 'single-shipper' "$LOCK_PY"; then
  ok "scoped-lock-single-flight"
else
  bad "scoped-lock-single-flight"
fi

if [[ -f "$FROZEN" ]] && \
   python3 -c "
import json, sys
data = json.load(open(sys.argv[1]))
ids = {e['id'] for e in data.get('fixtures', [])}
need = {'authoring-guard-fixtures', 'planning-currency-fixtures', 'doc-fixtures'}
assert need <= ids
" "$MANIFEST"; then
  ok "frozen-doc-ci-gates-unchanged"
else
  bad "frozen-doc-ci-gates-unchanged"
fi

exit "$FAIL"

"""
if __name__ == "__main__":
    raise SystemExit(main())
