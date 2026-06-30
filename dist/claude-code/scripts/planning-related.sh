#!/usr/bin/env bash
# Related-units scanner + pull-in proposal flow (PRD 035).
set -euo pipefail
_PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT="$(git -C "${PWD}" rev-parse --show-toplevel 2>/dev/null || echo "$_PLUGIN_ROOT")"
PY="$_PLUGIN_ROOT/scripts/planning_related.py"
cmd="${1:-}"
shift || true
export PYTHONPATH="$_PLUGIN_ROOT/scripts:${PYTHONPATH:-}"
case "$cmd" in
  scan|confirm|list-emission-points)
    exec python3 "$PY" "$ROOT" "$cmd" "$@"
    ;;
  -h|--help|"")
    cat <<'EOF'
Usage:
  planning-related.sh scan --path <artifact> [--mode creation|tasks-rescan] [--refresh-stale]
  planning-related.sh confirm --path <artifact> --accept <id>[,<id>...] [--accept-frozen-impact]
  planning-related.sh list-emission-points
EOF
    ;;
  *)
    echo "unknown command: $cmd" >&2
    exit 2
    ;;
esac
