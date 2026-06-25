#!/usr/bin/env bash
# Assert guides name /sw-deliver run for stop/confirm/auto (R78).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
FAIL=0

check_guide() {
  local label="$1" path="$2"
  if [[ ! -f "$path" ]]; then
    echo "FAIL doc-afterTasks-guides-deliver: missing $label"
    FAIL=1
    return
  fi
  local body
  body="$(cat "$path")"
  if echo "$body" | grep -q '/sw-deliver run' && \
     echo "$body" | grep -qE '`stop`|stop' && \
     echo "$body" | grep -qE '`confirm`|confirm' && \
     echo "$body" | grep -qE '`auto`|auto'; then
    echo "OK  doc-afterTasks-guides-deliver: $label documents /sw-deliver run for stop/confirm/auto"
  else
    echo "FAIL doc-afterTasks-guides-deliver: $label missing /sw-deliver run for all modes"
    FAIL=1
  fi
}

check_guide configuration "$ROOT/docs/guides/configuration.md"
check_guide getting-started "$ROOT/docs/guides/getting-started.md"

exit "$FAIL"
