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
# Fixtures for stabilize-merge-sync.sh and sw-stabilize merge-base triangulation.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=scripts/test/fixture-lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/fixture-lib.sh"
SYNC="$ROOT/scripts/stabilize-merge-sync.py"
STABILIZE="$(content_path commands/sw-stabilize.md)"
GATE="$ROOT/scripts/check_gate_lib.py"
FAIL=0

chmod +x "$SYNC" 2>/dev/null || true

# --- stabilize-merge-sync script exists ---
if [[ -f "$SYNC" ]]; then
  echo "OK  stabilize-merge-sync: script executable"
else
  echo "FAIL stabilize-merge-sync: missing or not executable"
  FAIL=1
fi

# --- sw-stabilize documents merge-base sync step 0 ---
if grep -q 'stabilize-merge-sync.py' "$STABILIZE" && \
   grep -qi 'merge-base sync' "$STABILIZE" && \
   grep -q 'conflictingFiles' "$STABILIZE" && \
   grep -q 'docs/prds/INDEX.md' "$STABILIZE"; then
  echo "OK  sw-stabilize-merge-base-sync: step 0 documented"
else
  echo "FAIL sw-stabilize-merge-base-sync: missing merge-base sync procedure"
  FAIL=1
fi

# --- check-gate surfaces merge-conflict ---
if grep -q 'merge-conflict' "$GATE" && grep -q 'mergeable' "$GATE"; then
  echo "OK  check-gate-merge-conflict: blocked verdict for CONFLICTING"
else
  echo "FAIL check-gate-merge-conflict: missing merge-conflict guard"
  FAIL=1
fi

# --- conflict-files offline probe (fixture repo) ---
FIX="$ROOT/scripts/test/fixtures/stabilize-merge-sync"
mkdir -p "$FIX"
if [[ ! -d "$FIX/repo/.git" ]]; then
  rm -rf "$FIX/repo"
  mkdir -p "$FIX/repo"
  git -C "$FIX/repo" init -q
  git -C "$FIX/repo" config user.email "fixture@test"
  git -C "$FIX/repo" config user.name "fixture"
  echo base > "$FIX/repo/shared.txt"
  git -C "$FIX/repo" add shared.txt
  git -C "$FIX/repo" commit -q -m "base"
  git -C "$FIX/repo" branch -M main
  git -C "$FIX/repo" checkout -q -b feature
  echo feature > "$FIX/repo/shared.txt"
  git -C "$FIX/repo" add shared.txt
  git -C "$FIX/repo" commit -q -m "feature"
  git -C "$FIX/repo" checkout -q main
  echo main > "$FIX/repo/shared.txt"
  git -C "$FIX/repo" add shared.txt
  git -C "$FIX/repo" commit -q -m "main advance"
fi

OUT=$(cd "$FIX/repo" && git checkout -q feature && bash "$SYNC" conflict-files --base main)
if echo "$OUT" | python3 -c "import json,sys; p=json.load(sys.stdin); assert 'shared.txt' in p"; then
  echo "OK  stabilize-merge-conflict-files: merge-tree lists conflicting paths"
else
  echo "FAIL stabilize-merge-conflict-files: expected shared.txt in $OUT"
  FAIL=1
fi

if [[ "$FAIL" -eq 0 ]]; then
  echo "stabilize-merge fixtures: PASS"
  exit 0
fi
echo "stabilize-merge fixtures: FAIL"
exit 1

"""
if __name__ == "__main__":
    raise SystemExit(main())
