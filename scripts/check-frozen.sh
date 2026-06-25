#!/usr/bin/env bash
# Reject diffs that modify frozen artifacts. CI authority for doc-freeze integrity (R9).
#
# Usage: check-frozen.sh [BASE_REF]
#   BASE_REF — git ref to diff against (default: origin/main or merge-base)
# Exit: 0 pass, 1 frozen violation, 2 usage/config error
set -euo pipefail

SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
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
    NR == 1 && /^---$/ { fm = 1; next }
    fm && /^---$/ { exit }
    fm && /^frozen:[[:space:]]*true/ { found = 1; exit }
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

is_checkbox_only_ref_change() {
  local path="$1"
  local base_ref="$2"
  local tmpdir
  tmpdir="$(mktemp -d)"
  if ! git show "$base_ref:$path" >"$tmpdir/old" 2>/dev/null; then
    rm -rf "$tmpdir"
    return 1
  fi
  if ! git show "HEAD:$path" >"$tmpdir/new" 2>/dev/null; then
    rm -rf "$tmpdir"
    return 1
  fi
  if python3 "$SCRIPT_ROOT/scripts/checkbox_diff.py" is-checkbox-only "$tmpdir/old" "$tmpdir/new" >/dev/null 2>&1; then
    rm -rf "$tmpdir"
    return 0
  fi
  rm -rf "$tmpdir"
  return 1
}

while IFS=$'\t' read -r status path; do
  [ -z "$path" ] && continue
  case "$path" in
    docs/plans/*) continue ;;
  esac
  case "$status" in
    A) continue ;;
    R*) continue ;;
    D|M)
      if git cat-file -e "$BASE:$path" 2>/dev/null; then
        if is_frozen_at_ref "$path" "$BASE"; then
          if is_checkbox_only_ref_change "$path" "$BASE"; then
            continue
          fi
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
