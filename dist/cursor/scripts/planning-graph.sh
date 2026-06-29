#!/usr/bin/env bash
# Planning graph + maintenance reconciler (PRD 033).
set -euo pipefail
_PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT="$(git -C "${PWD}" rev-parse --show-toplevel 2>/dev/null || echo "$_PLUGIN_ROOT")"
PY="$_PLUGIN_ROOT/scripts/planning_graph.py"
cmd="${1:-}"
shift || true
case "$cmd" in
  reconcile|cycle-check|doctor|relief-check)
    exec python3 "$PY" "$ROOT" "$cmd" "$@"
    ;;
  -h|--help|"")
    cat <<'EOF'
Usage:
  planning-graph.sh reconcile [--dry-run] [--commit] [--allow-default-branch --reason <text>] [--override-status <id> <from> <to> --reason <text>]
  planning-graph.sh cycle-check [--staged]
  planning-graph.sh doctor
  planning-graph.sh relief-check
EOF
    ;;
  *)
    echo "unknown command: $cmd" >&2
    exit 2
    ;;
esac
