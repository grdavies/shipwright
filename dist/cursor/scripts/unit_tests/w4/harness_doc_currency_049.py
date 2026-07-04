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
# PRD 049 — operator worktree contract doc acceptance (R1/R2).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=scripts/test/fixture-lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/fixture-lib.sh"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

LAYOUT="$ROOT/.sw/layout.md"
CONDUCTOR="$(content_path skills/conductor/SKILL.md)"
DELIVER="$(content_path skills/deliver/SKILL.md)"

check() {
  local name="$1" file="$2" pattern="$3"
  if grep -qE "$pattern" "$file" 2>/dev/null; then ok "$name"; else bad "$name"; fi
}

# doc-currency-049-contract-sections — .sw/layout.md (R1)
check "layout-operator-contract-heading" "$LAYOUT" '## Operator worktree contract'
check "layout-primary-checkout" "$LAYOUT" 'defaultBaseBranch'
check "layout-orchestrator-worktree" "$LAYOUT" '<slug>-orchestrator'
check "layout-phase-worktrees" "$LAYOUT" '<slug>-phase-'
check "layout-cursor-conductor-runtime" "$LAYOUT" 'conductor runtime'
check "layout-status-mirror-direction" "$LAYOUT" 'phase worktree → repo root'

# conductor/deliver skills echo (R2)
check "conductor-phase-worktree-ship" "$CONDUCTOR" 'phase worktree'
check "conductor-cursor-runtime" "$CONDUCTOR" 'conductor runtime'
check "conductor-no-main-impl-commits" "$CONDUCTOR" 'must not accumulate implementation commits'
check "deliver-primary-row" "$DELIVER" 'operator shell only'
check "deliver-status-mirror" "$DELIVER" 'phase → repo root'

# GAP-078 contradiction removed
if grep -q 'repo root with state synced' "$CONDUCTOR" 2>/dev/null; then
  bad "gap-078-conductor-repo-root-alternate"
else
  ok "gap-078-conductor-repo-root-alternate"
fi
if grep -q 'repo root with state synced' "$DELIVER" 2>/dev/null; then
  bad "gap-078-deliver-repo-root-alternate"
else
  ok "gap-078-deliver-repo-root-alternate"
fi

exit "$FAIL"
"""

if __name__ == "__main__":
    raise SystemExit(main())
