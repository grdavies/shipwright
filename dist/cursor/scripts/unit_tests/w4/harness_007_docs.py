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
# PRD 007 documentation presence (R37) — durable autonomy contract in user-facing guides.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FAIL=0

ok()  { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

check_doc() {
  local file="$1"
  shift
  local label="$1"
  shift
  if [[ ! -f "$file" ]]; then
    bad "007-docs-$label: missing file $file"
    return
  fi
  local text
  text="$(cat "$file")"
  for term in "$@"; do
    if ! echo "$text" | grep -qiE "$term"; then
      bad "007-docs-$label: missing topic '$term' in $file"
      return
    fi
  done
  ok "007-docs-$label"
}

check_doc "$ROOT/docs/guides/workflows.md" workflows \
  'deliver-loop' 'sw-cleanup' 'compound-ship' 'phase-worktree' 'merge gate'

check_doc "$ROOT/docs/guides/commands.md" commands \
  '/sw-cleanup' 'pre-merge' 'deliver-loop' 'secret-scan'

check_doc "$ROOT/docs/guides/getting-started.md" getting-started \
  '/sw-deliver' 'sw-cleanup'

check_doc "$ROOT/core/rules/sw-naming.mdc" naming \
  '/sw-cleanup' '/sw-deliver'

if grep -qE 'deliver-loop' "$ROOT/core/skills/deliver/SKILL.md" && \
   grep -qE 'status collect' "$ROOT/core/skills/deliver/SKILL.md" && \
   grep -qE 'secret-scan' "$ROOT/core/skills/deliver/SKILL.md"; then
  ok "007-docs-deliver-skill"
else
  bad "007-docs-deliver-skill"
fi

if [[ "$FAIL" -eq 0 ]]; then
  echo "007-docs fixtures: all passed"
  exit 0
fi
echo "007-docs fixtures: $FAIL failure(s)"
exit 1

"""

if __name__ == "__main__":
    raise SystemExit(main())
