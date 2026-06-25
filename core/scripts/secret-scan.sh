#!/usr/bin/env bash
# Pre-push secret scan chokepoint (R41/R50/R51). Fail-closed on scanner error.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GIT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$GIT_ROOT"
exec python3 "$ROOT/secret_scan.py" "$@"
