#!/usr/bin/env bash
# Assert README + docs/guides cover PRD 009 user-visible surfaces; no legacy pf- refs (R56–R57).
#
# Usage: docs-presence-check.sh
# Exit: 0 pass; 1 missing surface or legacy ref; 2 usage error
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FAIL=0

check_file() {
  local label="$1" path="$2" pattern="$3"
  if [[ ! -f "$path" ]]; then
    echo "FAIL $label: missing file $path"
    FAIL=1
    return
  fi
  if grep -qE "$pattern" "$path"; then
    echo "OK  $label"
  else
    echo "FAIL $label: pattern not found in $path"
    FAIL=1
  fi
}

DOCS=(
  "$ROOT/README.md"
  "$ROOT/docs/guides/getting-started.md"
  "$ROOT/docs/guides/workflows.md"
  "$ROOT/docs/guides/configuration.md"
  "$ROOT/docs/guides/commands.md"
)

for f in "${DOCS[@]}"; do
  check_file "deliver.autonomy in $(basename "$f")" "$f" 'deliver\.autonomy'
  check_file "legitimate.halt in $(basename "$f")" "$f" '(legitimate.halt|Legitimate.halt|legitimate halt)'
  check_file "living-doc in $(basename "$f")" "$f" '(living.doc|INDEX\.md|COMPLETION-LOG|GAP-BACKLOG)'
  check_file "frontmatter in $(basename "$f")" "$f" '(brainstorm:|prd:|frontmatter)'
done

LEGACY=0
for f in "${DOCS[@]}"; do
  if grep -qE '/pf-|pf-' "$f" 2>/dev/null; then
    echo "FAIL legacy pf- ref in $f"
    LEGACY=1
    FAIL=1
  fi
done
[[ "$LEGACY" -eq 0 ]] && echo "OK  user-docs-no-legacy-refs"

if [[ "$FAIL" -ne 0 ]]; then
  echo '{"verdict":"fail","action":"docs-presence-check"}'
  exit 1
fi

echo '{"verdict":"pass","action":"docs-presence-check"}'
exit 0
