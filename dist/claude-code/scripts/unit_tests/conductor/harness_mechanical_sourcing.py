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
# PRD 036 Phase 5 — mechanical sourcing audit (R19).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FAIL=0

ok()  { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

LAYOUT="$ROOT/.sw/layout.md"
CONDUCTOR="$ROOT/core/skills/conductor/SKILL.md"
DELIVER_CMD="$ROOT/core/commands/sw-deliver.md"
LOOP_PY="$ROOT/scripts/wave_deliver_loop.py"

if grep -qE 'sw-deliver-state\.<slug>|sw-deliver-runs/<phase-slug>/status\.json' "$LAYOUT" && \
   ! grep -qE 'parallel state store|second state file' "$CONDUCTOR"; then
  ok "no-new-parallel-state-store"
else
  bad "no-new-parallel-state-store"
fi

if grep -qE 'scripts/wave[.](sh|py).*deliver-loop' "$CONDUCTOR" && \
   grep -q 'does not maintain parallel state' "$CONDUCTOR" && \
   grep -q 'wave_\*\.py' "$CONDUCTOR"; then
  ok "conductor-delegates-wave-sh"
else
  bad "conductor-delegates-wave-sh"
fi

if grep -q 'save_state' "$LOOP_PY" && \
   grep -q 'compute_next_action' "$LOOP_PY" && \
   ! grep -qE 'hand-edit.*status\.json|manually edit status' "$DELIVER_CMD"; then
  ok "state-transitions-via-wave-py"
else
  bad "state-transitions-via-wave-py"
fi

exit "$FAIL"

"""

if __name__ == "__main__":
    raise SystemExit(main())
