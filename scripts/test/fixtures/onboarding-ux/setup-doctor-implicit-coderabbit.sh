#!/usr/bin/env bash
# Assert /sw-setup doctor surfaces implicit-coderabbit migration (R22).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
source "$ROOT/scripts/test/fixture-lib.sh"

SW_INIT="$(content_path commands/sw-init.md)"
FAIL=0

if grep -q 'CodeRabbit CLI present but `review.provider` unset' "$SW_INIT" && \
   grep -qi 'migration notice' "$SW_INIT"; then
  echo "OK  setup-doctor-implicit-coderabbit: doctor migration notice documented"
else
  echo "FAIL setup-doctor-implicit-coderabbit: missing implicit-coderabbit doctor notice"
  FAIL=1
fi

if grep -q 'implicit default flipped' "$SW_INIT" || grep -q 'set `review.provider` explicitly' "$SW_INIT"; then
  echo "OK  setup-doctor-implicit-coderabbit: explains explicit provider choice"
else
  echo "FAIL setup-doctor-implicit-coderabbit: missing explicit provider guidance"
  FAIL=1
fi

exit "$FAIL"
