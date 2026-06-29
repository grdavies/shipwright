#!/usr/bin/env bash
# PRD 034 — thin wrapper around the visibility resolver (single authority).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="${ROOT}/scripts:${PYTHONPATH:-}"
exec python3 "${ROOT}/scripts/planning_visibility.py" --root "$ROOT" "$@"
