#!/usr/bin/env bash
# Snapshot emittable plugin content to a parity manifest (relative-path<TAB>sha256).
#
# Captures the verbatim-copied subset the Cursor emitter will reproduce: commands/,
# skills/, rules/, agents/, providers/, and workflow scripts/ (excluding test harness
# and sync-local-install.sh). Hooks, docs/, and build tooling are out of scope.
#
# Usage:
#   scripts/snapshot-tree.sh [output-manifest]
#   scripts/snapshot-tree.sh -           # stdout
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:--}"

EMITTABLE_DIRS=(commands skills rules agents providers)

should_skip_relpath() {
  local relpath="$1"
  case "$relpath" in
    */__pycache__/* | */__pycache__ | *.pyc) return 0 ;;
    */.git/* | */node_modules/*) return 0 ;;
    scripts/test/* | scripts/test) return 0 ;;
    scripts/sync-local-install.sh) return 0 ;;
    hooks/* | hooks) return 0 ;;
  esac
  return 1
}

collect_emittable_relpaths() {
  local dir rel f
  for dir in "${EMITTABLE_DIRS[@]}"; do
    [ -d "$ROOT/$dir" ] || continue
    while IFS= read -r -d '' f; do
      rel="${f#"$ROOT"/}"
      should_skip_relpath "$rel" && continue
      printf '%s\n' "$rel"
    done < <(find "$ROOT/$dir" -type f -print0)
  done
  if [ -d "$ROOT/scripts" ]; then
    while IFS= read -r -d '' f; do
      rel="${f#"$ROOT"/}"
      should_skip_relpath "$rel" && continue
      printf '%s\n' "$rel"
    done < <(find "$ROOT/scripts" -type f -print0)
  fi
}

write_manifest() {
  local rel hash
  while IFS= read -r rel; do
    [ -n "$rel" ] || continue
    hash="$(shasum -a 256 "$ROOT/$rel" | awk '{print $1}')"
    printf '%s\t%s\n' "$rel" "$hash"
  done < <(collect_emittable_relpaths | LC_ALL=C sort -u)
}

if [ "$OUT" = "-" ]; then
  write_manifest
elif [ -n "$OUT" ]; then
  mkdir -p "$(dirname "$OUT")"
  write_manifest >"$OUT"
else
  write_manifest
fi
