#!/usr/bin/env bash
# Intra-phase fan-out guard + decision logging (PRD 023 R15–R17).
#
# Usage:
#   intra-phase-dispatch.sh stamp-context --run-dir <path> --conductor-mode inline|background_phase
#   intra-phase-dispatch.sh evaluate --context-json '{}' [--proposal-json '{}'] [--wave-slots N]
#     [--active-intra-phase N] [--run-dir <path>] [--record]
#   intra-phase-dispatch.sh check-nesting [--run-dir <path>] [--context-json '{}']
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$ROOT/scripts/intra_phase_dispatch.py" "$ROOT" "$@"
