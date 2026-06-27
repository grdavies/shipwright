#!/usr/bin/env bash
# Resolve host API token from configured env-var name (PRD 026 R8).
# Never prints the token value — only presence/degraded verdict JSON.
#
# Usage:
#   host_token.sh [--root PATH]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --root) ROOT="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,5p' "$0"
      exit 0
      ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

exec python3 "$ROOT/scripts/host_lib.py" --root "$ROOT" token-status
