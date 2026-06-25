#!/usr/bin/env bash
# Wave plan + integration helpers (multi-feature + phase-mode).
# Usage:
#   wave.sh plan --task-list docs/prds/.../tasks-....md [--type feat] [--dry-run] [--from N]
#   wave.sh plan --items 'A,B,C' --edges 'C:A'
#   wave.sh preflight --task-list ... | --items ...
#   wave.sh schedule --plan .cursor/sw-deliver-plan.json [--ceiling N]
#   wave.sh orchestrator provision|status ...
#   wave.sh phase provision --phase-id N [--plan ...] [--base <type>/<slug>]
#   wave.sh forward-merge --worktree <path> --base <type>/<slug>
#   wave.sh phase-teardown --worktree <path>|--name <name> [--force]
#   wave.sh assert-entry
#   wave.sh status collect --phase-slug <slug>
#   wave.sh phase dispatch-env --phase-slug <slug>
#   wave.sh merge gate-check|enqueue|exec|run-next|ancestry-check ...
#   wave.sh report terminal
#   wave.sh bookkeeping record|revert|projected ...
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
  orchestrator|forward-merge|phase-teardown|assert-entry)
    exec python3 "$ROOT/scripts/wave_lifecycle.py" "$ROOT" "$@"
    ;;
  phase)
    if [[ "${2:-}" == "dispatch-env" ]]; then
      exec python3 "$ROOT/scripts/wave_merge.py" "$ROOT" phase "${@:2}"
    fi
    exec python3 "$ROOT/scripts/wave_lifecycle.py" "$ROOT" phase "${@:2}"
    ;;
  status|report)
    exec python3 "$ROOT/scripts/wave_merge.py" "$ROOT" "$@"
    ;;
  merge)
    exec python3 "$ROOT/scripts/wave_merge.py" "$ROOT" merge "$@"
    ;;
  bookkeeping)
    exec python3 "$ROOT/scripts/wave_bookkeeping.py" "$ROOT" "${@:2}"
    ;;
esac
exec python3 "$ROOT/scripts/wave_deliver.py" "$ROOT" "$@"
