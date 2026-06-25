#!/usr/bin/env bash
# Assert stop is print-only with seed commit + /sw-deliver run; never onto main (R82).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$ROOT/scripts/test/fixture-lib.sh"

SW_DOC="$(content_path commands/sw-doc.md)"
FAIL=0

if grep -q '\*\*`stop`\*\*' "$SW_DOC" && grep -qi 'print-only' "$SW_DOC" && \
   grep -q 'docs-only seed command' "$SW_DOC" && \
   grep -q '/sw-deliver run <frozen-task-list-path>' "$SW_DOC"; then
  echo "OK  doc-afterTasks-seed-stop: stop prints seed + deliver commands"
else
  echo "FAIL doc-afterTasks-seed-stop: stop missing seed + deliver print guidance"
  FAIL=1
fi

if grep -q 'never onto `main`' "$SW_DOC" || grep -q 'never onto .main.' "$SW_DOC"; then
  echo "OK  doc-afterTasks-seed-stop: stop never directs spec onto main"
else
  echo "FAIL doc-afterTasks-seed-stop: stop must not seed onto main"
  FAIL=1
fi

if grep -q 'git checkout -B <type>/<slug>' "$SW_DOC" && grep -q 'git add docs/prds/<n>-<slug>/' "$SW_DOC"; then
  echo "OK  doc-afterTasks-seed-stop: stop prints docs-only commit onto feature branch"
else
  echo "FAIL doc-afterTasks-seed-stop: stop missing feature-branch commit command"
  FAIL=1
fi

exit "$FAIL"
