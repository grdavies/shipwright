#!/usr/bin/env bash
# Durable /sw-ship step state for phase-mode resume (R58).
#
# Usage:
#   ship-phase-steps.py init --phase SLUG [--out PATH] [--head SHA]
#   ship-phase-steps.py get [--phase SLUG] [--out PATH]
#   ship-phase-steps.py attempt --step STEP [--phase SLUG] [--out PATH]
#   ship-phase-steps.py advance --step STEP [--phase SLUG] [--out PATH]
#   ship-phase-steps.py resolve-resume [--from STEP] [--last-command CMD] [--phase SLUG] [--out PATH]
#   ship-phase-steps.py sync-state [--phase SLUG] [--out PATH]
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
