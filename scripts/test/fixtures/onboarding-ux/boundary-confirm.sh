#!/usr/bin/env bash
# Assert confirm mode strict ack and Go/silence → stop (R2, R3).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
source "$ROOT/scripts/test/fixture-lib.sh"

SW_DOC="$(content_path commands/sw-doc.md)"
FAIL=0

if grep -qE '\*\*`proceed`\*\*|\*\*proceed\*\*' "$SW_DOC" && grep -qE '\*\*`yes`\*\*|\*\*yes\*\*' "$SW_DOC"; then
  echo "OK  boundary-confirm: strict proceed/yes tokens documented"
else
  echo "FAIL boundary-confirm: missing proceed/yes ack contract"
  FAIL=1
fi

if grep -q '`Go`' "$SW_DOC" && grep -qi 'stop' "$SW_DOC"; then
  echo "OK  boundary-confirm: legacy Go maps to stop"
else
  echo "FAIL boundary-confirm: Go → stop mapping missing"
  FAIL=1
fi

if grep -qi 'silence' "$SW_DOC" && grep -qi 'ambiguous' "$SW_DOC"; then
  echo "OK  boundary-confirm: silence/ambiguous → stop"
else
  echo "FAIL boundary-confirm: silence/ambiguous stop behavior missing"
  FAIL=1
fi

exit "$FAIL"
