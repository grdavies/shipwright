#!/usr/bin/env bash
# Assert auto dispatch invokes /sw-deliver run; agent override recorded before dispatch (R76, R79).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$ROOT/scripts/test/fixture-lib.sh"

SW_DOC="$(content_path commands/sw-doc.md)"
FAIL=0

if grep -q '\*\*`auto`\*\*' "$SW_DOC" && \
   grep -q 'deliver-loop --task-list <frozen-task-list-path>' "$SW_DOC"; then
  echo "OK  doc-afterTasks-auto-deliver: auto dispatches deliver-loop"
else
  echo "FAIL doc-afterTasks-auto-deliver: auto missing /sw-deliver run dispatch"
  FAIL=1
fi

if grep -q 'implementing on branch' "$SW_DOC"; then
  echo "OK  doc-afterTasks-auto-deliver: branch notice before dispatch"
else
  echo "FAIL doc-afterTasks-auto-deliver: missing implementing on branch notice"
  FAIL=1
fi

if grep -q 'shipwright-state.sh override-add' "$SW_DOC" && \
   grep -q '\-\-after-tasks=auto' "$SW_DOC" && grep -qi 'before.*dispatch' "$SW_DOC"; then
  echo "OK  doc-afterTasks-auto-deliver: agent override recorded before dispatch"
else
  echo "FAIL doc-afterTasks-auto-deliver: agent override record missing"
  FAIL=1
fi

exit "$FAIL"
