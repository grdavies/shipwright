#!/usr/bin/env bash
# Assert stop mode prints /sw-deliver run with frozen task-list path (R77).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$ROOT/scripts/test/fixture-lib.sh"

SW_DOC="$(content_path commands/sw-doc.md)"
FAIL=0

if grep -q '\*\*`stop`\*\*' "$SW_DOC" && grep -qi 'print-only' "$SW_DOC" && \
   grep -q 'deliver-loop --task-list <frozen-task-list-path>' "$SW_DOC"; then
  echo "OK  doc-afterTasks-stop-deliver: stop prints deliver-loop"
else
  echo "FAIL doc-afterTasks-stop-deliver: stop missing /sw-deliver run next command"
  FAIL=1
fi

if grep -qi 'no repository mutation' "$SW_DOC" || grep -qi 'print-only' "$SW_DOC"; then
  echo "OK  doc-afterTasks-stop-deliver: stop does not mutate repository"
else
  echo "FAIL doc-afterTasks-stop-deliver: stop must be print-only"
  FAIL=1
fi

if grep -q 'frozen task-list path' "$SW_DOC" || grep -q 'frozen-task-list-path' "$SW_DOC"; then
  echo "OK  doc-afterTasks-stop-deliver: stop prints frozen task-list path"
else
  echo "FAIL doc-afterTasks-stop-deliver: missing task-list path in stop guidance"
  FAIL=1
fi

exit "$FAIL"
