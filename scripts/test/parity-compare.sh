#!/usr/bin/env bash
# Compare a directory tree against a parity manifest (relative-path<TAB>sha256).
#
# Usage: scripts/test/parity-compare.sh <target-dir> <manifest>
# Exit 0 on full match; non-zero with a named mismatch on first failure.
set -euo pipefail

TARGET="${1:?target directory required}"
MANIFEST="${2:?manifest path required}"

if [ ! -d "$TARGET" ]; then
  echo "parity-compare: target is not a directory: $TARGET" >&2
  exit 2
fi
if [ ! -f "$MANIFEST" ]; then
  echo "parity-compare: manifest not found: $MANIFEST" >&2
  exit 2
fi

TARGET="$(cd "$TARGET" && pwd)"

manifest_hash_for() {
  local path="$1"
  awk -F '\t' -v p="$path" '$1 == p { print $2; exit }' "$MANIFEST"
}

manifest_count() {
  awk -F '\t' 'NF >= 2 && $1 != "" { c++ } END { print c + 0 }' "$MANIFEST"
}

# Check every manifest entry exists with matching hash.
while IFS=$'\t' read -r path expected_hash; do
  [ -n "$path" ] || continue
  target_file="$TARGET/$path"
  if [ ! -f "$target_file" ]; then
    echo "parity-mismatch: missing file: $path"
    exit 1
  fi
  actual_hash="$(shasum -a 256 "$target_file" | awk '{print $1}')"
  if [ "$actual_hash" != "$expected_hash" ]; then
    echo "parity-mismatch: hash diff: $path"
    exit 1
  fi
done <"$MANIFEST"

# Detect extra files under emittable roots (same rules as snapshot-tree.sh).
should_skip_relpath() {
  local relpath="$1"
  case "$relpath" in
    */__pycache__/* | */__pycache__ | *.pyc) return 0 ;;
    scripts/test/* | scripts/test) return 0 ;;
    scripts/install.sh) return 0 ;;
    hooks/* | hooks) return 0 ;;
  esac
  return 1
}

check_extra_under() {
  local root="$1"
  [ -d "$TARGET/$root" ] || return 0
  local f rel
  while IFS= read -r -d '' f; do
    rel="${f#"$TARGET"/}"
    should_skip_relpath "$rel" && continue
    if [ -z "$(manifest_hash_for "$rel")" ]; then
      echo "parity-mismatch: extra file: $rel"
      exit 1
    fi
  done < <(find "$TARGET/$root" -type f -print0)
}

for root in commands skills rules agents providers scripts; do
  check_extra_under "$root"
done

echo "parity-match: tree matches manifest ($(manifest_count) files)"
exit 0
