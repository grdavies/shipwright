#!/usr/bin/env bash
# Operator escape hatch to clear an ambiguous inFlight tuple (PRD 032 R4).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT=""
REASON=""
DRY_RUN=0
COMMIT=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --reason)
      REASON="${2:-}"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --commit)
      COMMIT=1
      shift
      ;;
    --unit)
      UNIT="${2:-}"
      shift 2
      ;;
    -*)
      echo "unknown flag: $1" >&2
      exit 2
      ;;
    *)
      if [[ -z "$UNIT" ]]; then
        UNIT="$1"
      fi
      shift
      ;;
  esac
done
ARGS=(manual-clear --unit "$UNIT" --reason "$REASON")
[[ "$DRY_RUN" -eq 1 ]] && ARGS+=(--dry-run)
[[ "$COMMIT" -eq 1 ]] && ARGS+=(--commit)
exec python3 "$ROOT/scripts/inflight_reconcile.py" "$ROOT" "${ARGS[@]}"
