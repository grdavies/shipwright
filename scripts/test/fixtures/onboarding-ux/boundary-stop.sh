#!/usr/bin/env bash
# Assert stop mode halts with task-list path + next commands (R4).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
source "$ROOT/scripts/test/fixture-lib.sh"

SW_DOC="$(content_path commands/sw-doc.md)"
FAIL=0

if grep -q '\*\*`stop`\*\*' "$SW_DOC" && grep -qi 'halt' "$SW_DOC" && \
   grep -q '/sw-worktree' "$SW_DOC" && grep -q '/sw-start' "$SW_DOC"; then
  echo "OK  boundary-stop: stop halts with next commands"
else
  echo "FAIL boundary-stop: missing stop halt + handoff commands"
  FAIL=1
fi

if grep -qi 'no implementation dispatch' "$SW_DOC" || grep -qi 'No implementation' "$SW_DOC"; then
  echo "OK  boundary-stop: stop does not dispatch implementation"
else
  echo "FAIL boundary-stop: stop must not dispatch implementation"
  FAIL=1
fi

exit "$FAIL"
