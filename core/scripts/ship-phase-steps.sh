#!/usr/bin/env bash
# Durable /sw-ship step state for phase-mode resume (R58).
#
# Usage:
#   ship-phase-steps.sh init --phase SLUG [--out PATH] [--head SHA]
#   ship-phase-steps.sh get [--phase SLUG] [--out PATH]
#   ship-phase-steps.sh attempt --step STEP [--phase SLUG] [--out PATH]
#   ship-phase-steps.sh advance --step STEP [--phase SLUG] [--out PATH]
#   ship-phase-steps.sh resolve-resume [--from STEP] [--last-command CMD] [--phase SLUG] [--out PATH]
#   ship-phase-steps.sh sync-state [--phase SLUG] [--out PATH]
#
# Path: --out > $SW_RUN_DIR/ship-steps.json > .cursor/sw-deliver-runs/<phase>/ship-steps.json
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/scripts/ship_phase_steps.py"

if [[ ! -f "$PY" ]]; then
  echo '{"verdict":"fail","error":"ship_phase_steps.py missing"}' >&2
  exit 2
fi

exec python3 "$PY" "$ROOT" "$@"
