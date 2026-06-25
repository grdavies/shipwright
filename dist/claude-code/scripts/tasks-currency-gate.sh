#!/usr/bin/env bash
# Hard-block when frozen task checkboxes diverge from durable completion ledger (R15).
#
# Usage:
#   tasks-currency-gate.sh [--tasks-file PATH] [--state-root PATH]
#
# Exit: 0 pass; 1 divergence (hard block); 2 usage/config error
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TASKS_FILE=""
STATE_ROOT="$ROOT"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tasks-file) TASKS_FILE="${2:-}"; shift 2 ;;
    --state-root) STATE_ROOT="${2:-}"; shift 2 ;;
    -h|--help)
      sed -n '2,6p' "$0"
      exit 0
      ;;
    *) echo '{"verdict":"fail","error":"unknown argument"}' >&2; exit 2 ;;
  esac
done

if [[ -z "$TASKS_FILE" ]]; then
  STATE_JSON="$STATE_ROOT/.cursor/sw-deliver-state.json"
  if [[ ! -f "$STATE_JSON" ]]; then
    echo '{"verdict":"fail","error":"no --tasks-file and no deliver state"}' >&2
    exit 2
  fi
  TASKS_FILE="$(python3 -c "
import json
from pathlib import Path
s = json.loads(Path('$STATE_JSON').read_text())
print(s.get('source_task_list') or '')
")"
fi

if [[ -z "$TASKS_FILE" || ! -f "$TASKS_FILE" ]]; then
  echo '{"verdict":"fail","error":"task file not found"}' >&2
  exit 2
fi

exec python3 "$ROOT/scripts/wave_state.py" "$STATE_ROOT" ledger check \
  --tasks-file "$TASKS_FILE"
