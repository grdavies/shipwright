#!/usr/bin/env bash
# CLI wrapper for scripts/doc_format.py (PRD 031 R22/R13).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/scripts/doc_format.py"

if [[ "${1:-}" == "--check" ]]; then
  shift
  exec python3 "$PY" check "$@"
elif [[ "${1:-}" == "--write" ]]; then
  shift
  inplace=()
  if [[ "${1:-}" == "--inplace" ]]; then
    inplace=(--inplace)
    shift
  fi
  exec python3 "$PY" write "$@" "${inplace[@]}"
fi

exec python3 "$PY" "$@"
