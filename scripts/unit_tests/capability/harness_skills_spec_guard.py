#!/usr/bin/env python3
"""Skills-spec guard fixtures (PRD 064 R17)."""
from __future__ import annotations

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
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GUARD="$ROOT/scripts/skills-spec-guard.py"
FIX="$ROOT/scripts/test/fixtures/skills-spec"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

run_expect() {
  local name="$1" expect_ec="$2" tree_root="$3"
  shift 3
  set +e
  OUT=$(python3 "$GUARD" --repo-root "$tree_root" "$@" 2>&1)
  EC=$?
  set -e
  if [ "$EC" -eq "$expect_ec" ]; then
    ok "$name exit=$EC"
  else
    echo "FAIL $name expected exit=$expect_ec got exit=$EC"
    echo "$OUT"
    FAIL=1
  fi
}

run_expect skills-spec-live-tree-pass 0 "$ROOT"
run_expect skills-spec-pass-valid-core 0 "$FIX/pass-valid" --tree core/skills
run_expect skills-spec-pass-valid-cursor 0 "$FIX/pass-valid" --tree dist/cursor/skills
run_expect skills-spec-pass-valid-claude 0 "$FIX/pass-valid" --tree dist/claude-code/skills
run_expect skills-spec-fail-name-mismatch 20 "$FIX/fail-name-mismatch" --tree core/skills
run_expect skills-spec-fail-description-shape 20 "$FIX/fail-description-shape" --tree core/skills

exit "$FAIL"
"""

if __name__ == "__main__":
    raise SystemExit(main())
