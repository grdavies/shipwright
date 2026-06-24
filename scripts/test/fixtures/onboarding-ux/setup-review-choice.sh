#!/usr/bin/env bash
# Assert /sw-setup documents doc.afterTasks + review choice (R7, R15, R16, R19).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
source "$ROOT/scripts/test/fixture-lib.sh"

SW_SETUP="$(content_path commands/sw-setup.md)"
FAIL=0

if grep -q 'doc\.afterTasks' "$SW_SETUP" && grep -qE 'default \*\*`confirm`\*\*|default \*\*confirm\*\*' "$SW_SETUP" && \
   grep -qE '`stop` \| `confirm` \| `auto`' "$SW_SETUP"; then
  echo "OK  setup-review-choice: doc.afterTasks default confirm documented"
else
  echo "FAIL setup-review-choice: missing doc.afterTasks default confirm"
  FAIL=1
fi

if grep -qE '`coderabbit` \| `none`' "$SW_SETUP" && grep -qE 'default \*\*`none`\*\*|default \*\*none\*\*' "$SW_SETUP"; then
  echo "OK  setup-review-choice: review choice coderabbit|none, default none"
else
  echo "FAIL setup-review-choice: missing review choice or none default"
  FAIL=1
fi

if grep -q 'Do \*\*not\*\* offer a separate `disabled` choice' "$SW_SETUP"; then
  echo "OK  setup-review-choice: no separate disabled choice"
else
  echo "FAIL setup-review-choice: must reject separate disabled choice"
  FAIL=1
fi

if grep -q 'review\.provider: "none"' "$SW_SETUP" && grep -qi 'canonical opt-out' "$SW_SETUP"; then
  echo "OK  setup-review-choice: canonical opt-out documented"
else
  echo "FAIL setup-review-choice: missing canonical review.provider:none opt-out"
  FAIL=1
fi

exit "$FAIL"
