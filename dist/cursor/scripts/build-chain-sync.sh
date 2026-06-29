#!/usr/bin/env bash
# Unified build-chain sync: copy-to-core → generate --all → golden re-snapshot when dist changes (PRD 038 R7).
#
# Usage: scripts/build-chain-sync.sh
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

BEFORE="$(dist_hash)"

bash "$ROOT/scripts/copy-to-core.sh"
python3 -m sw generate --all

AFTER="$(dist_hash)"
if [ "$BEFORE" != "$AFTER" ]; then
  bash "$ROOT/scripts/snapshot-tree.sh" "$GOLDEN"
  echo "build-chain-sync: dist changed — updated $GOLDEN"
fi

echo "build-chain-sync: complete"
