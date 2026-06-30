#!/usr/bin/env bash
# Config-driven planning path resolution wrapper (PRD 031 R23/R7).
# Usage: planning_paths.py <command> [args...]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/scripts/planning_paths.py"

if [[ ! -f "$PY" ]]; then
  echo '{"verdict":"fail","error":"planning_paths.py missing"}' >&2
  exit 2
fi

exec python3 "$PY" "$ROOT" "$@"
