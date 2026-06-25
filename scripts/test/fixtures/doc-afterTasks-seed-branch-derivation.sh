#!/usr/bin/env bash
# Assert <type>/<slug> derived via shared /sw-deliver resolver (R81).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$ROOT/scripts/test/fixture-lib.sh"

SW_DOC="$(content_path commands/sw-doc.md)"
FAIL=0

if grep -q 'scripts/wave.sh preflight --task-list' "$SW_DOC" && \
   grep -q 'target.branch' "$SW_DOC" && \
   grep -q 'scripts/wave_deliver.py' "$SW_DOC"; then
  echo "OK  doc-afterTasks-seed-branch-derivation: uses shared deliver resolver"
else
  echo "FAIL doc-afterTasks-seed-branch-derivation: missing shared resolver reference"
  FAIL=1
fi

if grep -q 'do \*\*not\*\*' "$SW_DOC" && grep -qi 're-implement branch derivation' "$SW_DOC"; then
  echo "OK  doc-afterTasks-seed-branch-derivation: forbids divergent re-implementation"
else
  echo "FAIL doc-afterTasks-seed-branch-derivation: missing no re-implement guard"
  FAIL=1
fi

exit "$FAIL"
