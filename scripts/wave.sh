#!/usr/bin/env bash
# Wave plan + integration helpers (multi-feature + phase-mode).
# Usage:
#   wave.sh plan --task-list docs/prds/.../tasks-....md [--type feat] [--dry-run] [--from N]
#   wave.sh plan --items 'A,B,C' --edges 'C:A'
#   wave.sh preflight-base --target feat/<slug>
#   wave.sh dispatch preflight --dispatch-id <id> --agent <id> [--command <sw-*>] [--skill <name>]
#   wave.sh memory learnings distill|prepare ...
#   wave.sh schedule --plan .cursor/sw-deliver-plan.json [--ceiling N]  # parallel batches (R14/R44)
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
#   wave.sh watchdog check
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
#   wave.sh spec-seed --task-list docs/prds/.../tasks-....md [--dry-run]
#   wave.sh spec-seed --artifact docs/prds/.../<artifact>.md [--dry-run]
set -euo pipefail

PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT="$(git -C "$PWD" rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "$ROOT" ]]; then
  ROOT="$PLUGIN_ROOT"
fi
case "${1:-}" in
  spec-seed)
    exec python3 "$PLUGIN_ROOT/scripts/wave_spec_seed.py" "$ROOT" spec-seed "${@:2}"
    ;;
  deliver-loop)
    exec python3 "$PLUGIN_ROOT/scripts/wave_deliver_loop.py" "$ROOT" deliver-loop "${@:2}"
    ;;
  watchdog)
    exec python3 "$PLUGIN_ROOT/scripts/wave_deliver_loop.py" "$ROOT" watchdog "${@:2}"
    ;;
  state|lock|journal|log|ledger)
    exec python3 "$PLUGIN_ROOT/scripts/wave_state.py" "$ROOT" "$@"
    ;;
  tasks-currency)
    exec bash "$PLUGIN_ROOT/scripts/tasks-currency-gate.sh" "${@:2}"
    ;;
  docs-currency)
    exec bash "$PLUGIN_ROOT/scripts/docs-currency-gate.sh" "${@:2}"
    ;;
  living-docs)
    exec python3 "$PLUGIN_ROOT/scripts/wave_living_docs.py" "$ROOT" "${@:2}"
    ;;
  compound-ship|retrospective|completion)
    exec python3 "$PLUGIN_ROOT/scripts/wave_compound.py" "$ROOT" "$@"
    ;;
  orchestrator|forward-merge|phase-teardown|phase-teardown-run|assert-entry)
    exec python3 "$PLUGIN_ROOT/scripts/wave_lifecycle.py" "$ROOT" "$@"
    ;;
  phase)
    if [[ "${2:-}" == "dispatch-env" ]]; then
      exec python3 "$PLUGIN_ROOT/scripts/wave_merge.py" "$ROOT" phase "${@:2}"
    fi
    exec python3 "$PLUGIN_ROOT/scripts/wave_lifecycle.py" "$ROOT" phase "${@:2}"
    ;;
  status)
    exec python3 "$PLUGIN_ROOT/scripts/wave_merge.py" "$ROOT" status "${@:2}"
    ;;
  report)
    if [[ "${2:-}" == "blockers" ]]; then
      exec python3 "$PLUGIN_ROOT/scripts/wave_failure.py" "$ROOT" report blockers "${@:3}"
    fi
    exec python3 "$PLUGIN_ROOT/scripts/wave_merge.py" "$ROOT" report "${@:2}"
    ;;
  merge)
    exec python3 "$PLUGIN_ROOT/scripts/wave_merge.py" "$ROOT" merge "${@:2}"
    ;;
  bookkeeping)
    exec python3 "$PLUGIN_ROOT/scripts/wave_bookkeeping.py" "$ROOT" "${@:2}"
    ;;
  preflight-base)
    exec python3 "$PLUGIN_ROOT/scripts/wave_preflight.py" "$ROOT" base-check "${@:2}"
    ;;
  dispatch)
    exec python3 "$PLUGIN_ROOT/scripts/wave_preflight.py" "$ROOT" dispatch "${@:2}"
    ;;
  memory)
    exec python3 "$PLUGIN_ROOT/scripts/wave_memory.py" "$ROOT" "$@"
    ;;
  resume|ack)
    exec python3 "$PLUGIN_ROOT/scripts/wave_terminal.py" "$ROOT" "$@"
    ;;
  verify|blast-radius|revert|stabilize)
    exec python3 "$PLUGIN_ROOT/scripts/wave_failure.py" "$ROOT" "$@"
    ;;
  terminal)
    if [[ "${2:-}" == "deny" ]]; then
      exec python3 "$PLUGIN_ROOT/scripts/wave_failure.py" "$ROOT" terminal "${@:2}"
    fi
    exec python3 "$PLUGIN_ROOT/scripts/wave_terminal.py" "$ROOT" terminal "${@:2}"
    ;;
esac
exec python3 "$PLUGIN_ROOT/scripts/wave_deliver.py" "$ROOT" "$@"
