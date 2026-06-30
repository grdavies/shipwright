#!/usr/bin/env bash
# Unified build-chain sync: copy-to-core → generate --all → golden re-snapshot when dist changes (PRD 038 R7).
#
# Usage: scripts/build-chain-sync.sh [--check]
#   --check  verify parity only (no mutations); exit 20 on drift (R25).
# Exit: 0 on success; non-zero on any step failure.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GOLDEN="$ROOT/scripts/test/fixtures/parity/cursor-golden.manifest"

dist_hash() {
  if [ ! -d "$ROOT/dist/cursor" ] && [ ! -d "$ROOT/dist/claude-code" ]; then
    echo ""
    return 0
  fi
  find "$ROOT/dist/cursor" "$ROOT/dist/claude-code" -type f -print0 2>/dev/null \
    | sort -z \
    | xargs -0 shasum -a 256 2>/dev/null \
    | shasum -a 256 \
    | awk '{print $1}'
}

CHECK_ONLY=0
if [[ "${1:-}" == "--check" ]]; then
  CHECK_ONLY=1
fi

if [[ "$CHECK_ONLY" -eq 1 ]]; then
  FAIL=0
  bash "$ROOT/scripts/build-chain-sot-lint.sh" >/dev/null 2>&1 || FAIL=1
  bash "$ROOT/scripts/test/run-core-scripts-parity-fixtures.sh" >/dev/null 2>&1 || FAIL=1
  bash "$ROOT/scripts/test/run-parity-fixtures.sh" >/dev/null 2>&1 || FAIL=1
  BEFORE="$(dist_hash)"
  python3 -m sw generate --all >/dev/null 2>&1 || FAIL=1
  AFTER="$(dist_hash)"
  if [[ -n "$BEFORE" && "$BEFORE" != "$AFTER" ]]; then
    FAIL=1
  fi
  if [[ "$FAIL" -ne 0 ]]; then
    echo "build-chain-sync --check: parity drift detected" >&2
    exit 20
  fi
  echo "build-chain-sync --check: parity OK"
  exit 0
fi


BEFORE="$(dist_hash)"

bash "$ROOT/scripts/copy-to-core.sh"
python3 -m sw generate --all

AFTER="$(dist_hash)"
if [ "$BEFORE" != "$AFTER" ]; then
  bash "$ROOT/scripts/snapshot-tree.sh" "$GOLDEN"
  echo "build-chain-sync: dist changed — updated $GOLDEN"
fi

echo "build-chain-sync: complete"
