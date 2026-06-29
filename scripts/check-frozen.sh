#!/usr/bin/env bash
# Reject diffs that modify frozen artifacts. CI authority for doc-freeze integrity (R9).
# Operates only on the committed git snapshot — never calls the memory provider (PRD 015 R5).
#
# Usage:
#   check-frozen.sh [BASE_REF]
#   check-frozen.sh freeze-commit --artifact <path>
#
#   BASE_REF — git ref to diff against (default: origin/main or merge-base)
#   freeze-commit — verdict-independent wrapper around spec-seed (PRD 013 R4); warns on failure, exits 0
# Exit: 0 pass, 1 frozen violation, 2 usage/config error
set -euo pipefail

SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${1:-}" == "freeze-commit" ]]; then
  shift
  ARTIFACT=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --artifact) ARTIFACT="${2:-}"; shift 2 ;;
      *) echo '{"verdict":"fail","reason":"unknown freeze-commit argument"}' >&2; exit 2 ;;
    esac
  done
  if [[ -z "$ARTIFACT" ]]; then
    echo '{"verdict":"fail","reason":"freeze-commit requires --artifact <path>"}' >&2
    exit 2
  fi
  OUT=""
  EC=0
  set +e
  OUT=$(bash "$SCRIPT_ROOT/scripts/wave.sh" spec-seed --artifact "$ARTIFACT" 2>&1)
  EC=$?
  set -e
  NEED_WARN=0
  if [[ "$EC" -ne 0 ]]; then
    NEED_WARN=1
  elif ! echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get('verdict') in ('pass', 'ok') else 1)" 2>/dev/null; then
    NEED_WARN=1
  fi
  if [[ "$NEED_WARN" -eq 1 ]]; then
    python3 - <<'PY' "$EC" "$OUT"
import json, sys
ec, detail = int(sys.argv[1]), sys.argv[2]
print(json.dumps({
    "verdict": "warn",
    "action": "freeze-commit",
    "reason": "branch or commit failed; freeze stamp still stands (verdict-independent)",
    "exitCode": ec,
    "detail": detail.strip(),
}))
PY
    exit 0
  fi
  echo "$OUT"
  exit 0
  echo "$OUT"
  exit 0
fi
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
BASE="${1:-}"

if [ -z "$BASE" ]; then
  RESOLVER="$SCRIPT_ROOT/scripts/resolve-base-branch.sh"
  if [[ -x "$RESOLVER" ]]; then
    if OUT=$(bash "$RESOLVER" diff-base 2>/dev/null); then
      BASE=$(echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('range','').split('..')[0])" 2>/dev/null || true)
    fi
  fi
fi

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

# Allow a frozen-doc change iff normalizing the BASE content yields exactly the HEAD
# content — i.e. the diff is pure doc-format canonicalization (GAP-045 bridge); semantics
# are provably unchanged because the canonical form of the old bytes equals the new bytes.
is_format_normalization_only() {
  local path="$1"
  local base_ref="$2"
  local tmpdir rc=1
  tmpdir="$(mktemp -d)"
  if git show "$base_ref:$path" >"$tmpdir/old" 2>/dev/null \
    && git show "HEAD:$path" >"$tmpdir/new" 2>/dev/null \
    && python3 "$SCRIPT_ROOT/scripts/doc_format.py" write "$tmpdir/old" >"$tmpdir/old_norm" 2>/dev/null \
    && cmp -s "$tmpdir/old_norm" "$tmpdir/new"; then
    rc=0
  fi
  rm -rf "$tmpdir"
  return "$rc"
}

# Precompute the set of PRD directories that gain an ADDED frozen amendment in this diff.
# A frozen task-list refresh is the sanctioned regeneration that accompanies an amendment
# (PRD 013 freeze-safety lineage); it is permitted only when bound to such an amendment.
AMENDED_DIRS=()
while IFS=$'\t' read -r a_status a_path; do
  [ -z "$a_path" ] && continue
  case "$a_status" in
    A)
      case "$a_path" in
        docs/prds/*/amendments/*.md)
          if git show "HEAD:$a_path" 2>/dev/null | awk '
            NR == 1 && /^---$/ { fm = 1; next }
            fm && /^---$/ { exit }
            fm && /^frozen:[[:space:]]*true/ { found = 1; exit }
            END { exit !found }
          '; then
            AMENDED_DIRS+=("${a_path%/amendments/*}")
          fi
          ;;
      esac
      ;;
  esac
done <<< "$DIFF_OUT"

dir_has_added_frozen_amendment() {
  local d="$1" x
  for x in "${AMENDED_DIRS[@]:-}"; do
    [ "$x" = "$d" ] && return 0
  done
  return 1
}

# Allow a frozen task-list change when an added frozen amendment sits under the same PRD
# directory in this diff and the refreshed task list is well-formed (doc-format --check).
is_amendment_companion_tasklist() {
  local path="$1"
  case "$(basename "$path")" in
    tasks-*.md) ;;
    *) return 1 ;;
  esac
  dir_has_added_frozen_amendment "$(dirname "$path")" || return 1
  python3 "$SCRIPT_ROOT/scripts/doc_format.py" check "$path" >/dev/null 2>&1 || return 1
  return 0
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
          if is_format_normalization_only "$path" "$BASE"; then
            continue
          fi
          if is_amendment_companion_tasklist "$path"; then
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
