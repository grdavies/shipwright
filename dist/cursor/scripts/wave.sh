#!/usr/bin/env bash
# Wave plan + integration helpers (multi-feature + phase-mode).
# Usage:
#   wave.sh plan --task-list docs/prds/.../tasks-....md [--type feat] [--dry-run] [--from N]
#   wave.sh plan --items 'A,B,C' --edges 'C:A'
#   wave.sh preflight --task-list ... | --items ...
#   wave.sh integration --stamp <stamp> --branches 'branch1,branch2'
#   wave.sh state init|get|phase|terminal ...
#   wave.sh lock acquire|release|status ...
#   wave.sh journal begin|complete|status ...
#   wave.sh log tail [--lines N]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
case "${1:-}" in
  state|lock|journal|log)
    exec python3 "$ROOT/scripts/wave_state.py" "$ROOT" "$@"
    ;;
esac
exec python3 "$ROOT/scripts/wave_deliver.py" "$ROOT" "$@"
