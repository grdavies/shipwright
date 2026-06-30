#!/usr/bin/env bash
# Planning graph + maintenance reconciler (PRD 033).
set -euo pipefail
_PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT="$(git -C "${PWD}" rev-parse --show-toplevel 2>/dev/null || echo "$_PLUGIN_ROOT")"
PY="$_PLUGIN_ROOT/scripts/planning_graph.py"
cmd="${1:-}"
shift || true
case "$cmd" in
  reconcile)
    exec python3 "$_PLUGIN_ROOT/scripts/reconcile.py" planning-reconcile "$@"
    ;;
  cycle-check|doctor|relief-check)
    exec python3 "$PY" "$ROOT" "$cmd" "$@"
    ;;
  next)
    exec python3 "$_PLUGIN_ROOT/scripts/wave_deliver.py" "$ROOT" next "$@"
    ;;
  posture)
    exec python3 "$_PLUGIN_ROOT/scripts/planning_autonomy.py" "$ROOT" posture
    ;;
  paths)
    if [[ $# -eq 0 ]]; then set -- dirs; fi
    exec bash "$_PLUGIN_ROOT/scripts/planning_paths.sh" "$@"
    ;;
  -h|--help|"")
    cat <<'EOF'
Usage:
  planning-graph.sh reconcile [--dry-run] [--commit] [--allow-default-branch --reason <text>] [--override-status <id> <from> <to> --reason <text>]
  planning-graph.sh cycle-check [--staged]
  planning-graph.sh doctor
  planning-graph.sh relief-check
  planning-graph.sh next [--override --override-reason <text>]
  planning-graph.sh posture
  planning-graph.sh paths <planning_paths.py subcommand> [args...]
EOF
    ;;
  *)
    echo "unknown command: $cmd" >&2
    exit 2
    ;;
esac
