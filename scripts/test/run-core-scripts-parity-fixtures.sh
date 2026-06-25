#!/usr/bin/env bash
# Assert core/scripts/ mirrors repo-root scripts/ per scripts/copy-to-core.sh rules.
#
# Usage: run-core-scripts-parity-fixtures.sh
# Exit: 0 pass; 1 drift detected
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC="$ROOT/scripts"
DST="$ROOT/core/scripts"
FAIL=0

should_skip_relpath() {
  case "$1" in
    test/* | test) return 0 ;;
    check-frozen.sh) return 0 ;;
    */__pycache__/* | */__pycache__ | *.pyc) return 0 ;;
  esac
  return 1
}

if [ ! -d "$DST" ]; then
  echo "FAIL core-scripts-parity missing core/scripts/ — run scripts/copy-to-core.sh"
  exit 1
fi

while IFS= read -r -d '' file; do
  rel="${file#"$SRC"/}"
  should_skip_relpath "$rel" && continue
  if [ ! -f "$DST/$rel" ]; then
    echo "FAIL core-scripts-parity missing core/scripts/$rel"
    FAIL=1
    continue
  fi
  if ! cmp -s "$file" "$DST/$rel"; then
    echo "FAIL core-scripts-parity drift core/scripts/$rel (run scripts/copy-to-core.sh)"
    FAIL=1
  fi
done < <(find "$SRC" -type f -print0)

while IFS= read -r -d '' file; do
  rel="${file#"$DST"/}"
  should_skip_relpath "$rel" && continue
  if [ "$rel" = "check-frozen.sh" ]; then
    echo "FAIL core-scripts-parity unexpected core/scripts/check-frozen.sh"
    FAIL=1
    continue
  fi
  if [ ! -f "$SRC/$rel" ]; then
    echo "FAIL core-scripts-parity orphan core/scripts/$rel"
    FAIL=1
  fi
done < <(find "$DST" -type f -print0)

if [ "$FAIL" -eq 0 ]; then
  echo "OK  core-scripts-parity scripts/ matches core/scripts/"
fi

exit "$FAIL"
