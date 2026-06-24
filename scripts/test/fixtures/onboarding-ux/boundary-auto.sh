#!/usr/bin/env bash
# Assert auto mode dispatches implementation loop with branch notice (R5).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
source "$ROOT/scripts/test/fixture-lib.sh"

SW_DOC="$(content_path commands/sw-doc.md)"
FAIL=0

if grep -q '\*\*`auto`\*\*' "$SW_DOC" && grep -q 'implementing on branch' "$SW_DOC"; then
  echo "OK  boundary-auto: branch notice before dispatch"
else
  echo "FAIL boundary-auto: missing implementing on branch notice"
  FAIL=1
fi

if grep -q '/sw-worktree' "$SW_DOC" && grep -q '/sw-ship' "$SW_DOC" && \
   grep -qi 'dispatch' "$SW_DOC"; then
  echo "OK  boundary-auto: dispatches implementation loop"
else
  echo "FAIL boundary-auto: missing dispatch handoff"
  FAIL=1
fi

if grep -q 'sw-assert-worktree' "$SW_DOC"; then
  echo "OK  boundary-auto: worktree invariant referenced"
else
  echo "FAIL boundary-auto: worktree guard not referenced in sw-doc"
  FAIL=1
fi

exit "$FAIL"
