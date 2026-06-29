#!/usr/bin/env bash
# PRD 034 R14 — visibility emission-point call-site map lint.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MAP="${1:-docs/prds/034-visibility-and-planning-store/call-site-map.md}"
shift || true
export PYTHONPATH="${ROOT}/scripts:${PYTHONPATH:-}"
exec python3 "${ROOT}/scripts/visibility-callsite-lint.py" --root "$ROOT" --map "$MAP" "$@"
