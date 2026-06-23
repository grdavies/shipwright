#!/usr/bin/env bash
# Reject diffs that modify frozen artifacts. CI authority for doc-freeze integrity (R9).
#
# Usage: check-frozen.sh [BASE_REF]
#   BASE_REF — git ref to diff against (default: origin/main or merge-base)
# Exit: 0 pass, 1 frozen violation, 2 usage/config error
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
BASE="${1:-}"

if [ -z "$BASE" ]; then
  if git rev-parse --verify origin/main >/dev/null 2>&1; then
    BASE="$(git merge-base HEAD origin/main 2>/dev/null || echo origin/main)"
  else
    BASE="HEAD~1"
  fi
fi

is_frozen_at_ref() {
  local file="$1" ref="$2"
  git show "$ref:$file" 2>/dev/null | awk '
    /^---$/ { fm=1; next }
    fm && /^---$/ { exit }
    fm && /^frozen:[[:space:]]*true/ { found=1; exit }
    END { exit !found }
  '
}

VIOLATIONS=()
DIFF_OUT=""
if ! DIFF_OUT=$(git diff --name-status "$BASE"...HEAD 2>/dev/null); then
  if ! DIFF_OUT=$(git diff --name-status "$BASE" HEAD 2>/dev/null); then
    echo '{"verdict":"fail","reason":"unable to compute diff against base"}' >&2
    exit 2
  fi
fi

while IFS=$'\t' read -r status path; do
  [ -z "$path" ] && continue
  case "$status" in
    A) continue ;;
    D|M|R*)
      if git cat-file -e "$BASE:$path" 2>/dev/null; then
        if is_frozen_at_ref "$path" "$BASE"; then
          VIOLATIONS+=("$path")
        fi
      fi
      ;;
  esac
done <<< "$DIFF_OUT"

if [ "${#VIOLATIONS[@]}" -gt 0 ]; then
  echo '{"verdict":"fail","reason":"frozen artifact modified","files":['
  for i in "${!VIOLATIONS[@]}"; do
    [ "$i" -gt 0 ] && echo -n ","
    printf '"%s"' "${VIOLATIONS[$i]}"
  done
  echo ']}'
  exit 1
fi

echo '{"verdict":"pass","reason":"no frozen artifacts modified"}'
exit 0
