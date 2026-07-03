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
# Golden tests for the byte-parity harness (snapshot + compare).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SNAPSHOT="$ROOT/scripts/snapshot-tree.sh"
COMPARE="$ROOT/scripts/test/parity-compare.sh"
FIX="$ROOT/scripts/test/fixtures/parity"
GOLDEN="$FIX/cursor-golden.manifest"

chmod +x "$SNAPSHOT" "$COMPARE"

FAIL=0
TMP_BASE="$(mktemp -d "${TMPDIR:-/tmp}/sw-parity-fix.XXXXXX")"
trap 'rm -rf "$TMP_BASE"' EXIT

run_expect() {
  local name="$1" expect_ec="$2"
  shift 2
  set +e
  if [[ "${1:-}" == *.py ]]; then
    OUT=$(python3 "$@" 2>&1)
  else
    OUT=$("$@" 2>&1)
  fi
  EC=$?
  set -e
  if [ "$EC" -eq "$expect_ec" ]; then
    echo "OK  $name exit=$EC"
  else
    echo "FAIL $name expected exit=$expect_ec got exit=$EC"
    echo "$OUT"
    FAIL=1
  fi
}

# Fixture tree: happy match
HAPPY="$TMP_BASE/happy-tree"
mkdir -p "$HAPPY/commands"
echo 'cmd body' >"$HAPPY/commands/sw-test.md"
MANIFEST_HAPPY="$TMP_BASE/happy.manifest"
printf 'commands/sw-test.md\t%s\n' "$(shasum -a 256 "$HAPPY/commands/sw-test.md" | awk '{print $1}')" >"$MANIFEST_HAPPY"
run_expect happy-match 0 "$COMPARE" "$HAPPY" "$MANIFEST_HAPPY"

# Missing file
MISSING="$TMP_BASE/missing-tree"
mkdir -p "$MISSING/commands"
run_expect missing-file 1 "$COMPARE" "$MISSING" "$MANIFEST_HAPPY"

# Extra file
EXTRA="$TMP_BASE/extra-tree"
cp -R "$HAPPY" "$EXTRA"
echo 'extra' >"$EXTRA/commands/extra.md"
run_expect extra-file 1 "$COMPARE" "$EXTRA" "$MANIFEST_HAPPY"

# Hash diff
DIFF="$TMP_BASE/diff-tree"
cp -R "$HAPPY" "$DIFF"
echo 'changed' >"$DIFF/commands/sw-test.md"
run_expect hash-diff 1 "$COMPARE" "$DIFF" "$MANIFEST_HAPPY"

# Deterministic re-snapshot
TMP_MANIFEST="$(mktemp)"
python3 "$SNAPSHOT" "$TMP_MANIFEST"
python3 "$SNAPSHOT" "${TMP_MANIFEST}.2"
if cmp -s "$TMP_MANIFEST" "${TMP_MANIFEST}.2"; then
  echo "OK  snapshot-deterministic identical across two runs"
else
  echo "FAIL snapshot-deterministic manifests differ between runs"
  FAIL=1
fi
rm -f "$TMP_MANIFEST" "${TMP_MANIFEST}.2"

# Live repo golden manifest matches dist/cursor/ (post-flip install source).
if [ ! -f "$GOLDEN" ]; then
  echo "FAIL cursor-golden.manifest missing at $GOLDEN"
  FAIL=1
else
  run_expect cursor-golden-vs-dist 0 "$COMPARE" "$ROOT/dist/cursor" "$GOLDEN"
fi

exit "$FAIL"

"""

if __name__ == "__main__":
    raise SystemExit(main())
