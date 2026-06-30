#!/usr/bin/env bash
# Back-compat wrapper for resolve-intensity.py command lookups.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || $# -eq 0 ]]; then
  cat <<'EOF'
Usage: communication-resolve.py <command> [--config <path>] [--child <atomic-command>]

Deprecated wrapper; forwards to scripts/resolve-intensity.py.
EOF
  exit 0
fi

command_name="$1"
shift
exec bash "$ROOT/scripts/resolve-intensity.py" --command "$command_name" "$@"
