#!/usr/bin/env bash
# Pre-push secret scan chokepoint (R41/R50/R51). Fail-closed on scanner error.
# inFlight tuple bodies are validated at write time by inflight_signal.py (PRD 032 R18).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GIT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$GIT_ROOT"
if [[ "${1:-}" == "inflight-tuple" ]]; then
  shift
  exec python3 "$ROOT/inflight_signal.py" "$GIT_ROOT" validate "$@"
fi
exec python3 "$ROOT/secret_scan.py" "$@"
