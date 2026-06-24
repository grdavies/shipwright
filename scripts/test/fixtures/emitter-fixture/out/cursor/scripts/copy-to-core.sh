#!/usr/bin/env bash
# Additively copy emittable workflow content into core/ (root layout stays authoritative).
#
# Usage: scripts/copy-to-core.sh
# Idempotent: re-run refreshes core/ copies from the live root layout.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CORE="$ROOT/core"

mkdir -p "$CORE"

for dir in commands skills rules agents providers; do
  [ -d "$ROOT/$dir" ] || continue
  mkdir -p "$CORE/$dir"
  rsync -a --delete "$ROOT/$dir/" "$CORE/$dir/"
done

mkdir -p "$CORE/scripts"
rsync -a --delete \
  --exclude 'test/' \
  "$ROOT/scripts/" "$CORE/scripts/"

if [ -d "$ROOT/.pf" ]; then
  mkdir -p "$CORE/pf-reference"
  rsync -a --delete "$ROOT/.pf/" "$CORE/pf-reference/"
fi

echo "copy-to-core: synced emittable content -> $CORE"
