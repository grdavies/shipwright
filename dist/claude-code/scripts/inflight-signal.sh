#!/usr/bin/env bash
# Committed in-flight signal writer CLI (PRD 032 R1/R2/R11).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$ROOT/scripts/inflight_signal.py" "$ROOT" "$@"
