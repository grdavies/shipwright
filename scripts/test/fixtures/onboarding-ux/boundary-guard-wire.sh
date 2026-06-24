#!/usr/bin/env bash
# Assert worktree guard wired at implementation entry (R6, R27 task 4.5).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
source "$ROOT/scripts/test/fixture-lib.sh"

SW_EXECUTE="$(content_path commands/sw-execute.md)"
SW_START="$(content_path commands/sw-start.md)"
FAIL=0

if grep -q 'sw-assert-worktree.sh' "$SW_EXECUTE"; then
  echo "OK  boundary-guard-wire: sw-execute invokes worktree guard"
else
  echo "FAIL boundary-guard-wire: sw-execute missing sw-assert-worktree"
  FAIL=1
fi

if grep -q 'sw-assert-worktree.sh' "$SW_START"; then
  echo "OK  boundary-guard-wire: sw-start invokes worktree guard"
else
  echo "FAIL boundary-guard-wire: sw-start missing sw-assert-worktree"
  FAIL=1
fi

exit "$FAIL"
