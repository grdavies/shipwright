#!/usr/bin/env python3
"""Ported fixture suite (R27) — embedded harness executed without on-disk shell files."""
from __future__ import annotations

import os
import re
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
# PRD 036 Phase 5 — deliver invariant regression guard (R22).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FAIL=0

ok()  { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

SW_DELIVER="$ROOT/core/commands/sw-deliver.md"
SCAN="$ROOT/scripts/secret-scan.sh"
PUSH="$ROOT/scripts/git-push.sh"
LOCK_PY="$ROOT/scripts/wave_lock.py"
FROZEN="$ROOT/scripts/check-frozen.sh"
MANIFEST="$ROOT/core/sw-reference/pr-test-plan.manifest.json"

if grep -qE 'does not bypass.*main|auto-merge to `main`|human merge gate' "$SW_DELIVER" && \
   grep -q 'halts at the human merge gate' "$SW_DELIVER"; then
  ok "human-merge-gate-unchanged"
else
  bad "human-merge-gate-unchanged"
fi

if [[ -x "$SCAN" ]] && [[ -x "$PUSH" ]] && grep -q 'secret-scan' "$PUSH"; then
  ok "secret-scan-push-chokepoint"
else
  bad "secret-scan-push-chokepoint"
fi

if grep -q 'sw-deliver-locks' "$LOCK_PY" && grep -q 'single-shipper' "$LOCK_PY"; then
  ok "scoped-lock-single-flight"
else
  bad "scoped-lock-single-flight"
fi

if [[ -x "$FROZEN" ]] && \
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
