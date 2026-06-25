#!/usr/bin/env bash
# Safe cleanup of merged branches, stale worktrees, and terminal deliver run-state (R28–R34, R56).
# Never uses rm -rf on worktrees — git worktree remove + prune only.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$(git rev-parse --show-toplevel 2>/dev/null || echo "$ROOT")"
exec python3 "$ROOT/scripts/cleanup_lib.py" "$PWD" "$@"
