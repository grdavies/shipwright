#!/usr/bin/env python3
"""Fixture suite for PRD 053 execute orchestration (phase 1+)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR.parent))

from _fixture_lib import repo_root
from _harness_patch import patch_source as _patch_source

SCENARIOS = (
    "wave-merge-no-regression",
)


def main() -> int:
    root = repo_root(__file__)
    env = os.environ.copy()
    env["ROOT"] = str(root)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(root / "scripts" / "test"), str(root / "scripts"), env.get("PYTHONPATH", "")) if p
    )
    only = [a for a in sys.argv[1:] if not a.startswith("-")]
    src = _patch_source(_SOURCE, root)
    if only:
        for name in only:
            if name not in SCENARIOS:
                print(f"unknown scenario: {name}", file=sys.stderr)
                return 2
        env["SCENARIO_FILTER"] = ",".join(only)
    completed = subprocess.run(
        ["bash", "-c", src],
        cwd=str(root),
        env=env,
        shell=False,
    )
    return completed.returncode


_SOURCE = r"""
#!/usr/bin/env bash
# PRD 053 execute orchestration fixtures.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WM="$ROOT/scripts/wave_merge.py"
FAIL=0
FILTER="${SCENARIO_FILTER:-}"

ok()  { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

want() {
  local id="$1"
  if [ -n "$FILTER" ]; then
    case ",$FILTER," in
      *,"$id",*) return 0 ;;
      *) return 1 ;;
    esac
  fi
  return 0
}

# --- wave-merge-no-regression (SC7) ---
if want wave-merge-no-regression; then
MERGE_Q_FIX=$(mktemp -d)
(
  cd "$MERGE_Q_FIX"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  echo base >f.txt && git add f.txt && git commit -q -m init
  git branch -m feat/demo
  git checkout -q -b feat/demo-phase-alpha
  echo phase >>f.txt && git add f.txt && git commit -q -m phase
  git checkout -q feat/demo
  mkdir -p .cursor
  echo '{"target":{"branch":"feat/demo"},"orchestratorWorktree":{"path":"'"$MERGE_Q_FIX"'"}}' >.cursor/sw-deliver-state.json
  if OUT=$(python3 "$WM" "$MERGE_Q_FIX" merge exec --phase-slug alpha --phase-branch feat/demo-phase-alpha --target feat/demo 2>/dev/null) && \
     echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='pass' and d['method']=='merge'"; then
  :
  else
    exit 1
  fi
  if python3 "$WM" "$MERGE_Q_FIX" merge ancestry-check --phase-branch feat/demo-phase-alpha --target feat/demo 2>/dev/null \
    | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['merged'] is True"; then
  :
  else
    exit 1
  fi
) && ok "wave-merge-no-regression" || bad "wave-merge-no-regression"
rm -rf "$MERGE_Q_FIX"
fi

exit "$FAIL"
"""

if __name__ == "__main__":
    raise SystemExit(main())
