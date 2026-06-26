#!/usr/bin/env bash
# PRD 007 documentation presence (R37) — durable autonomy contract in user-facing guides.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FAIL=0

ok()  { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

check_doc() {
  local file="$1"
  shift
  local label="$1"
  shift
  if [[ ! -f "$file" ]]; then
    bad "007-docs-$label: missing file $file"
    return
  fi
  local text
  text="$(cat "$file")"
  for term in "$@"; do
    if ! echo "$text" | grep -qiE "$term"; then
      bad "007-docs-$label: missing topic '$term' in $file"
      return
    fi
  done
  ok "007-docs-$label"
}

check_doc "$ROOT/docs/guides/workflows.md" workflows \
  'deliver-loop' 'sw-cleanup' 'compound-ship' 'phase-worktree' 'merge gate'

check_doc "$ROOT/docs/guides/commands.md" commands \
  '/sw-cleanup' 'pre-merge' 'deliver-loop' 'secret-scan'

check_doc "$ROOT/docs/guides/getting-started.md" getting-started \
  '/sw-deliver' 'sw-cleanup'

check_doc "$ROOT/core/rules/sw-naming.mdc" naming \
  '/sw-cleanup' '/sw-deliver'

if grep -qE 'deliver-loop' "$ROOT/core/skills/deliver/SKILL.md" && \
   grep -qE 'status collect' "$ROOT/core/skills/deliver/SKILL.md" && \
   grep -qE 'secret-scan' "$ROOT/core/skills/deliver/SKILL.md"; then
  ok "007-docs-deliver-skill"
else
  bad "007-docs-deliver-skill"
fi

if [[ "$FAIL" -eq 0 ]]; then
  echo "007-docs fixtures: all passed"
  exit 0
fi
echo "007-docs fixtures: $FAIL failure(s)"
exit 1
