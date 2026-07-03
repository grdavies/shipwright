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
# PRD 033 phase 7 — operator doc acceptance fixtures (R25).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=scripts/test/fixture-lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/fixture-lib.sh"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

LIVING="$(content_path skills/living-status/SKILL.md)"
DELIVER="$(content_path commands/sw-deliver.md)"
STATUS="$(content_path commands/sw-status.md)"
WF="$ROOT/docs/guides/workflows.md"
GS="$ROOT/docs/guides/getting-started.md"

check() {
  local name="$1" file="$2" pattern="$3"
  if grep -q "$pattern" "$file" 2>/dev/null; then ok "$name"; else bad "$name"; fi
}

# doc-currency-033-sections (living-status + commands)
check "living-status-reconciler" "$LIVING" "planning-graph reconcile"
check "living-status-inflight" "$LIVING" "inFlight"
check "living-status-archive" "$LIVING" "INDEX-archive"
check "living-status-gap-units" "$LIVING" "planning_gap_capture"
check "sw-deliver-next" "$DELIVER" "wave_deliver.py.*next"
check "sw-deliver-dependency-gate" "$DELIVER" "dependency-gate"
check "sw-deliver-soft-enforce" "$DELIVER" "planning.autonomy"
check "sw-deliver-run-start" "$DELIVER" "Run-start"
check "sw-status-gap-echo" "$STATUS" "planning/INDEX"
check "sw-status-override-drift" "$STATUS" "override drift"

# doc-currency-033-sections (guides)
check "workflows-lifecycle" "$WF" "Planning lifecycle (PRD 033)"
check "workflows-deliver-next" "$WF" "/sw-deliver next"
check "workflows-reconciler" "$WF" "planning-graph reconcile"
check "workflows-legacy-projection" "$WF" "read-only projection"
check "getting-started-reconciler" "$GS" "maintenance reconciler"
check "getting-started-planning-index" "$GS" "docs/planning/INDEX"

# doc-currency-033-a1-sections (R36)
check "living-status-a1-monotonic" "$LIVING" "Monotonic terminal status"
check "living-status-a1-default-branch" "$LIVING" "Default-branch reconcile refusal"
check "living-status-a1-finalize" "$LIVING" "Completion finalize chokepoint"
check "sw-status-a1-playbook" "$STATUS" "Post-merge playbook (A1)"
RETRO="$(content_path commands/sw-retrospective.md)"
check "sw-retrospective-a1" "$RETRO" "Post-merge INDEX safety (A1)"

exit "$FAIL"

"""

if __name__ == "__main__":
    raise SystemExit(main())
