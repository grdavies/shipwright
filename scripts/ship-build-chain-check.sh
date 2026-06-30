#!/usr/bin/env bash
# Fail closed when build-chain paths drift before ship commit (PRD 035 A1 R25).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="${BUILD_CHAIN_PATHS_MANIFEST:-$ROOT/core/sw-reference/build-chain-paths.json}"
[[ -f "$MANIFEST" ]] || { echo "ship-build-chain-check: missing $MANIFEST" >&2; exit 2; }
command -v jq >/dev/null 2>&1 || { echo "ship-build-chain-check: jq required" >&2; exit 2; }

touches_build_chain() {
  local path prefix
  for path in "$@"; do
    [[ -z "$path" ]] && continue
    while IFS= read -r prefix; do
      [[ -z "$prefix" ]] && continue
      if [[ "$path" == "$prefix"* ]]; then
        return 0
      fi
    done < <(jq -r '.pathPrefixes[]?' "$MANIFEST")
  done
  return 1
}

CHANGED=()
while IFS= read -r line; do
  [[ -z "$line" ]] && continue
  CHANGED+=("${line:3}")
done < <(git -C "$ROOT" status --porcelain)

if ! touches_build_chain "${CHANGED[@]}"; then
  echo "ship-build-chain-check: no build-chain paths in diff — skip"
  exit 0
fi

if bash "$ROOT/scripts/build-chain-sync.sh" --check; then
  echo "ship-build-chain-check: build-chain parity OK"
  exit 0
fi

echo "ship-build-chain-check: FAIL — run bash scripts/build-chain-sync.sh" >&2
exit 20
