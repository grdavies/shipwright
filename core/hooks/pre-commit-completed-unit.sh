#!/usr/bin/env bash
# Pre-commit guard: reject mutations to complete planning units (PRD 032 R9/R12).
# Chained from core/hooks/pre-commit after pre-commit-frozen.sh.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GUARD_PY="$PLUGIN_ROOT/scripts/authoring_guard.py"

if [[ ! -f "$GUARD_PY" ]]; then
  echo "sw-completed-unit: authoring_guard.py missing; refusing commit" >&2
  exit 1
fi

STAGED="$(git diff --cached --name-only)"
[[ -z "$STAGED" ]] && exit 0

python3 "$GUARD_PY" "$ROOT" check-staged
