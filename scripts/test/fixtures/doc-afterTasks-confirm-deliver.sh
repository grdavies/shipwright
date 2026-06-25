#!/usr/bin/env bash
# Assert confirm dispatch invokes /sw-deliver run, not legacy chain (R76).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$ROOT/scripts/test/fixture-lib.sh"

SW_DOC="$(content_path commands/sw-doc.md)"
FAIL=0

if grep -q '\*\*`confirm`\*\*' "$SW_DOC" && \
   grep -q 'deliver-loop --task-list <frozen-task-list-path>' "$SW_DOC"; then
  echo "OK  doc-afterTasks-confirm-deliver: confirm dispatches deliver-loop"
else
  echo "FAIL doc-afterTasks-confirm-deliver: confirm missing /sw-deliver run dispatch"
  FAIL=1
fi

if grep -q 'Do \*\*not\*\* recommend `/sw-worktree`' "$SW_DOC" || \
   grep -q 'Do \*\*not\*\* recommend' "$SW_DOC"; then
  echo "OK  doc-afterTasks-confirm-deliver: legacy chain not primary path"
else
  echo "FAIL doc-afterTasks-confirm-deliver: missing legacy-chain non-primary guard"
  FAIL=1
fi

if ! grep -q 'confirm.*`/sw-worktree`.*dispatch' "$SW_DOC" 2>/dev/null; then
  echo "OK  doc-afterTasks-confirm-deliver: confirm does not dispatch worktree chain"
else
  echo "FAIL doc-afterTasks-confirm-deliver: confirm still dispatches legacy chain"
  FAIL=1
fi

exit "$FAIL"
