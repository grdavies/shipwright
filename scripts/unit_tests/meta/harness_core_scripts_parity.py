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
# Assert core/scripts/ mirrors repo-root scripts/ per scripts/copy-to-core.sh rules.
#
# Usage: run-core-scripts-parity-fixtures.sh
# Exit: 0 pass; 1 drift detected
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC="$ROOT/scripts"
DST="$ROOT/core/scripts"
FAIL=0

should_skip_relpath() {
  case "$1" in
    test/* | test | tests/* | tests | unit_tests/* | unit_tests) return 0 ;;
    check-frozen.sh|check-frozen.py) return 0 ;;
    */__pycache__/* | */__pycache__ | *.pyc) return 0 ;;
  esac
  return 1
}

if [ ! -d "$DST" ]; then
  echo "FAIL core-scripts-parity missing core/scripts/ — run scripts/copy-to-core.sh"
  exit 1
fi

while IFS= read -r -d '' file; do
  rel="${file#"$SRC"/}"
  should_skip_relpath "$rel" && continue
  if [ ! -f "$DST/$rel" ]; then
    echo "FAIL core-scripts-parity missing core/scripts/$rel"
    FAIL=1
    continue
  fi
  if ! cmp -s "$file" "$DST/$rel"; then
    echo "FAIL core-scripts-parity drift core/scripts/$rel (run scripts/copy-to-core.sh)"
    FAIL=1
  fi
done < <(find "$SRC" -type f -print0)

while IFS= read -r -d '' file; do
  rel="${file#"$DST"/}"
  should_skip_relpath "$rel" && continue
  if [ "$rel" = "check-frozen.sh" ]; then
    echo "FAIL core-scripts-parity unexpected core/scripts/check-frozen.sh"
    FAIL=1
    continue
  fi
  if [ ! -f "$SRC/$rel" ]; then
    echo "FAIL core-scripts-parity orphan core/scripts/$rel"
    FAIL=1
  fi
done < <(find "$DST" -type f -print0)

if [ "$FAIL" -eq 0 ]; then
  echo "OK  core-scripts-parity scripts/ matches core/scripts/"
fi

exit "$FAIL"

"""

if __name__ == "__main__":
    raise SystemExit(main())
