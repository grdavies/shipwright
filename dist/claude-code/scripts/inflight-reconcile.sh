#!/usr/bin/env bash
# Self-heal / staleness reconcile for committed inFlight tuples (PRD 032 R3/R4).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$ROOT/scripts/inflight_reconcile.py" "$ROOT" "$@"
