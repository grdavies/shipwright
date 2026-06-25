#!/usr/bin/env bash
# Wave plan + integration helpers (multi-feature + phase-mode).
# Usage:
#   wave.sh plan --task-list docs/prds/.../tasks-....md [--type feat] [--dry-run] [--from N]
#   wave.sh plan --items 'A,B,C' --edges 'C:A'
#   wave.sh preflight-base --target feat/<slug>
#   wave.sh memory learnings distill|prepare ...
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
#   wave.sh verify run|run-after-merge ...
#   wave.sh blast-radius apply|dependents ...
#   wave.sh report blockers
#   wave.sh revert phase ...
#   wave.sh terminal pr prepare|gate|status
#   wave.sh terminal deny ...
#   wave.sh resume reconcile
#   wave.sh ack status|check|complete
#   wave.sh stabilize route ...
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
  status)
    exec python3 "$ROOT/scripts/wave_merge.py" "$ROOT" status "$@"
    ;;
  report)
    if [[ "${2:-}" == "blockers" ]]; then
      exec python3 "$ROOT/scripts/wave_failure.py" "$ROOT" report blockers "${@:3}"
    fi
    exec python3 "$ROOT/scripts/wave_merge.py" "$ROOT" report "$@"
    ;;
  merge)
    exec python3 "$ROOT/scripts/wave_merge.py" "$ROOT" merge "$@"
    ;;
  bookkeeping)
    exec python3 "$ROOT/scripts/wave_bookkeeping.py" "$ROOT" "${@:2}"
    ;;
  preflight-base)
    exec python3 "$ROOT/scripts/wave_preflight.py" "$ROOT" base-check "${@:2}"
    ;;
  memory)
    exec python3 "$ROOT/scripts/wave_memory.py" "$ROOT" "$@"
    ;;
  resume|ack)
    exec python3 "$ROOT/scripts/wave_terminal.py" "$ROOT" "$@"
    ;;
  verify|blast-radius|revert|stabilize)
    exec python3 "$ROOT/scripts/wave_failure.py" "$ROOT" "$@"
    ;;
  terminal)
    if [[ "${2:-}" == "deny" ]]; then
      exec python3 "$ROOT/scripts/wave_failure.py" "$ROOT" terminal "${@:2}"
    fi
    exec python3 "$ROOT/scripts/wave_terminal.py" "$ROOT" terminal "${@:2}"
    ;;
esac
exec python3 "$ROOT/scripts/wave_deliver.py" "$ROOT" "$@"
