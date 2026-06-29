#!/usr/bin/env bash
# CI scan for materialized private-body prefix + golden markers in PR diffs (PRD 034 R8).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/scripts:${PYTHONPATH:-}"
BASE="${1:-origin/main}"
exec python3 "$ROOT/scripts/planning_materialize.py" --root "$ROOT" scan-diff --base "$BASE"
