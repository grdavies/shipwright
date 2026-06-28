#!/usr/bin/env bash
# Migration bridge: promote legacy deliver in-progress markers into INDEX inFlight (PRD 032 R10).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$ROOT/scripts/inflight_migration_bridge.py" "$ROOT" "$@"
