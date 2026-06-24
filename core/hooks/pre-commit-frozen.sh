#!/usr/bin/env bash
# Local pre-commit hook: block commits touching frozen artifacts.
# Early warning only — bypassable via --no-verify. CI check-frozen.sh is authoritative.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
CHECK="$ROOT/scripts/check-frozen.sh"

if [ ! -x "$CHECK" ]; then
  echo "pf-freeze: check-frozen.sh missing or not executable; refusing commit" >&2
  exit 1
fi

STAGED="$(git diff --cached --name-only)"
[ -z "$STAGED" ] && exit 0

is_frozen_at_head() {
  local path="$1"
  git show "HEAD:$path" 2>/dev/null | awk '
    /^---$/ { fm=1; next }
    fm && /^---$/ { exit }
    fm && /^frozen:[[:space:]]*true/ { found=1; exit }
    END { exit !found }
  '
}

VIOLATIONS=()
while IFS= read -r path; do
  [ -z "$path" ] && continue
  # New files (not at HEAD) are allowed — mirrors check-frozen status A
  if ! git cat-file -e "HEAD:$path" 2>/dev/null; then
    continue
  fi
  if is_frozen_at_head "$path"; then
    if git diff --cached --quiet -- "$path" 2>/dev/null; then
      : # no staged change
    else
      VIOLATIONS+=("$path")
    fi
  fi
done <<< "$STAGED"

if [ "${#VIOLATIONS[@]}" -gt 0 ]; then
  echo "pf-freeze: refusing commit — frozen artifact(s) modified:" >&2
  printf '  %s\n' "${VIOLATIONS[@]}" >&2
  echo "Use /pf-amend for post-freeze changes. Bypass with --no-verify (CI will still block)." >&2
  exit 1
fi

exit 0
