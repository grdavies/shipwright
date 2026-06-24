#!/usr/bin/env bash
# Cross-platform guardrail enforcement matrix (Cursor + Claude Code adapters).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FIX="$ROOT/scripts/test/fixtures/guardrail-matrix"

echo "guardrail-matrix: driving shared scenarios (see $FIX/README.md)"

if bash "$ROOT/scripts/test/run-hook-fixtures.sh"; then
  echo "OK  guardrail-matrix cursor+claude shared scenarios"
else
  echo "FAIL guardrail-matrix hook scenarios"
  exit 1
fi

exit 0
