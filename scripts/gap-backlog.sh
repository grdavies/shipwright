#!/usr/bin/env bash
# GAP-BACKLOG list/check/flip helper (PRD 035 A2 R53–R54).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(git -C "${PWD}" rev-parse --show-toplevel 2>/dev/null || echo "$ROOT")"
PY="$ROOT/scripts/gap_backlog.py"
cmd="${1:-}"; shift || true
case "$cmd" in
  list|check|flip) exec python3 "$PY" --root "$REPO_ROOT" "$cmd" "$@" ;;
  -h|--help|"") sed -n '2,8p' "$0"; exit 0 ;;
  *) echo '{"verdict":"fail","error":"unknown subcommand"}' >&2; exit 2 ;;
esac
