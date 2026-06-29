#!/usr/bin/env bash
# Validate core/sw-reference/build-chain-sot.json (PRD 038 R12).
#
# Usage: scripts/build-chain-sot-lint.sh
# Exit: 0 pass; 1 validation failure
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="$ROOT/core/sw-reference/build-chain-sot.json"
SW_REF="$ROOT/core/sw-reference"
FAIL=0

if [[ ! -f "$MANIFEST" ]]; then
  echo "FAIL build-chain-sot-lint: missing $MANIFEST"
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "FAIL build-chain-sot-lint: jq required"
  exit 1
fi

if ! jq -e '.version and .coreAuthoredAllowlist' "$MANIFEST" >/dev/null 2>&1; then
  echo "FAIL build-chain-sot-lint: manifest missing version or coreAuthoredAllowlist"
  exit 1
fi

seen=""
while IFS= read -r entry; do
  [[ -z "$entry" ]] && continue
  if printf '%s\n' "$seen" | grep -Fxq "$entry"; then
    echo "FAIL build-chain-sot-lint: duplicate allowlist entry: $entry"
    FAIL=1
    continue
  fi
  seen="${seen}${entry}"$'\n'

  case "$entry" in
    */)
      dir="${entry%/}"
      if [[ ! -d "$SW_REF/$dir" ]]; then
        echo "FAIL build-chain-sot-lint: allowlist directory missing: core/sw-reference/$dir"
        FAIL=1
      fi
      ;;
    *)
      if [[ ! -f "$SW_REF/$entry" ]]; then
        echo "FAIL build-chain-sot-lint: allowlist file missing: core/sw-reference/$entry"
        FAIL=1
      fi
      ;;
  esac
done < <(jq -r '.coreAuthoredAllowlist[]' "$MANIFEST")

if [[ "$FAIL" -eq 0 ]]; then
  echo "OK  build-chain-sot-lint"
fi
exit "$FAIL"
