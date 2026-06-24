#!/usr/bin/env bash
# Verify core/ additive copies match the live root layout and golden manifest coverage.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CORE="$ROOT/core"
GOLDEN="$ROOT/scripts/test/fixtures/parity/cursor-golden.manifest"
COMPARE="$ROOT/scripts/test/parity-compare.sh"

FAIL=0

if [ ! -d "$CORE" ]; then
  echo "FAIL core/ directory missing — run scripts/copy-to-core.sh"
  exit 1
fi

# Every golden manifest path must exist under core/ with identical hash.
while IFS=$'\t' read -r path hash; do
  [ -n "$path" ] || continue
  core_file="$CORE/$path"
  root_file="$ROOT/$path"
  if [ ! -f "$core_file" ]; then
    echo "FAIL relocation-coverage missing core/$path"
    FAIL=1
    continue
  fi
  if [ ! -f "$root_file" ]; then
    echo "FAIL relocation-coverage root missing $path"
    FAIL=1
    continue
  fi
  core_hash="$(shasum -a 256 "$core_file" | awk '{print $1}')"
  root_hash="$(shasum -a 256 "$root_file" | awk '{print $1}')"
  if [ "$core_hash" != "$root_hash" ]; then
    echo "FAIL relocation-hash core/$path differs from root"
    FAIL=1
  fi
done <"$GOLDEN"

if [ "$FAIL" -eq 0 ]; then
  echo "OK  relocation-coverage all golden paths present in core/ with matching hashes"
fi

# Root layout still matches golden manifest (live plugin unchanged).
if bash "$COMPARE" "$ROOT" "$GOLDEN"; then
  echo "OK  root-layout parity unchanged"
else
  echo "FAIL root-layout parity"
  FAIL=1
fi

# Existing hook fixtures still pass on root-loaded plugin.
if bash "$ROOT/scripts/test/run-hook-fixtures.sh"; then
  echo "OK  hook-fixtures on root layout"
else
  echo "FAIL hook-fixtures on root layout"
  FAIL=1
fi

exit "$FAIL"
