#!/usr/bin/env bash
# Assert seed excludes brainstorms; agent auto records seed commit branch+SHA (R83).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$ROOT/scripts/test/fixture-lib.sh"

SW_DOC="$(content_path commands/sw-doc.md)"
FAIL=0

if grep -q 'docs/brainstorms/\*\*' "$SW_DOC" && grep -qi 'Exclude' "$SW_DOC"; then
  echo "OK  doc-afterTasks-seed-brainstorm-excluded: brainstorm path excluded"
else
  echo "FAIL doc-afterTasks-seed-brainstorm-excluded: brainstorm exclusion missing"
  FAIL=1
fi

if grep -q 'untracked or ignored path' "$SW_DOC" || grep -q 'untracked/ignored' "$SW_DOC"; then
  echo "OK  doc-afterTasks-seed-brainstorm-excluded: untracked/ignored excluded"
else
  echo "FAIL doc-afterTasks-seed-brainstorm-excluded: untracked/ignored exclusion missing"
  FAIL=1
fi

if grep -q 'seed commit (branch + SHA)' "$SW_DOC" && \
   grep -q 'shipwright-state.sh write' "$SW_DOC" && \
   grep -q '\-\-after-tasks=auto' "$SW_DOC"; then
  echo "OK  doc-afterTasks-seed-brainstorm-excluded: agent auto records seed commit"
else
  echo "FAIL doc-afterTasks-seed-brainstorm-excluded: seed commit run-record missing"
  FAIL=1
fi

exit "$FAIL"
