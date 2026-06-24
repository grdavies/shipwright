#!/usr/bin/env bash
# Assert user-facing docs cover onboarding UX (R23).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
FAIL=0

check_file() {
  local label="$1" path="$2"
  if [[ ! -f "$path" ]]; then
    echo "FAIL user-docs-onboarding: missing $label at $path"
    FAIL=1
    return
  fi
  local body
  body="$(cat "$path")"

  if echo "$body" | grep -qE 'afterTasks|`stop`|stop.*confirm.*auto|confirm.*auto'; then
    echo "OK  user-docs-onboarding: $label documents doc.afterTasks modes"
  else
    echo "FAIL user-docs-onboarding: $label missing doc.afterTasks boundary modes"
    FAIL=1
  fi

  if echo "$body" | grep -qi 'worktree\|bare `main`\|bare main'; then
    echo "OK  user-docs-onboarding: $label documents worktree invariant"
  else
    echo "FAIL user-docs-onboarding: $label missing worktree invariant"
    FAIL=1
  fi

  if echo "$body" | grep -q '/sw-tasks' && echo "$body" | grep -qi 'single-pass\|single pass\|one pass'; then
    echo "OK  user-docs-onboarding: $label documents single-pass /sw-tasks"
  else
    echo "FAIL user-docs-onboarding: $label missing single-pass /sw-tasks"
    FAIL=1
  fi

  if echo "$body" | grep -q 'review\.provider' && echo "$body" | grep -q '`none`'; then
    echo "OK  user-docs-onboarding: $label documents review.provider none"
  else
    echo "FAIL user-docs-onboarding: $label missing review.provider none"
    FAIL=1
  fi

  if echo "$body" | grep -qi 'canonical opt-out\|canonical way to disable'; then
    echo "OK  user-docs-onboarding: $label documents canonical opt-out"
  else
    echo "FAIL user-docs-onboarding: $label missing canonical review opt-out"
    FAIL=1
  fi
}

check_file README "$ROOT/README.md"
check_file getting-started "$ROOT/documentation/getting-started.md"
check_file commands "$ROOT/documentation/commands.md"

# Cross-doc: CodeRabbit opt-in (not default) mentioned somewhere user-facing
if rg -l 'opt-in|default.*`none`|default is `none`' "$ROOT/README.md" "$ROOT/documentation" >/dev/null 2>&1; then
  echo "OK  user-docs-onboarding: CodeRabbit opt-in / none default surfaced"
else
  echo "FAIL user-docs-onboarding: must document none default or CodeRabbit opt-in"
  FAIL=1
fi

exit "$FAIL"
