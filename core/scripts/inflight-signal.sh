#!/usr/bin/env bash
# CLI for committed in-flight signal (PRD 032).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GIT_ROOT="$(git -C "$ROOT" rev-parse --show-toplevel)"
exec python3 "$ROOT/scripts/inflight_signal.py" "$GIT_ROOT" "$@"
