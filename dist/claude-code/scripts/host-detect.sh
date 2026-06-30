#!/usr/bin/env bash
# Auto-detect host provider from configured git remote (PRD 026 R6, R7).
#
# Usage:
#   host-detect.py [--root PATH]
#
# Exit 0 with JSON on stdout; non-zero on resolution failure.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --root) ROOT="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,6p' "$0"
      exit 0
      ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

exec python3 "$ROOT/scripts/host_lib.py" --root "$ROOT" resolve
