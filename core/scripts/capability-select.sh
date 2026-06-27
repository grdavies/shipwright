#!/usr/bin/env bash
# Deterministic capability selector entrypoint (PRD 021 TR3).
#
# Usage:
#   capability-select.sh [--context PATH] [--context-json JSON] [--index PATH]
#     [--run-dir PATH] [--resume] [--skip-freshness]
#
# Exit: 0 with canonical JSON on stdout; non-zero on freshness/validation failure.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$ROOT/scripts/capability_select.py" --root "$ROOT" "$@"
