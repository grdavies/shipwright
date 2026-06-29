#!/usr/bin/env bash
# Write durable /sw-ship phase-mode terminal status for /sw-deliver (R48/R18/R47, R13).
#
# Usage:
#   ship-phase-status.sh --verdict merge-ready-green|blocked [--cause TEXT] [--phase SLUG]
#     [--out PATH] [--head SHA] [--pr N] [--gate-json PATH]
#
# Path resolution: --out > $SW_RUN_DIR/status.json > .cursor/sw-deliver-runs/<phase>/status.json
# Phase slug: --phase > $SW_PHASE_SLUG > shipwright-state phaseSlug > "unknown"
#
# Exit: 0 on write success; 2 on usage/validation error.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERDICT=""
CAUSE=""
PHASE=""
OUT=""
HEAD=""
PR=""
GATE_JSON=""
SHIP_STEPS_PATH="${SHIP_STEPS_PATH:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --verdict) VERDICT="${2:-}"; shift 2 ;;
    --cause) CAUSE="${2:-}"; shift 2 ;;
    --phase) PHASE="${2:-}"; shift 2 ;;
    --out) OUT="${2:-}"; shift 2 ;;
    --head) HEAD="${2:-}"; shift 2 ;;
    --pr) PR="${2:-}"; shift 2 ;;
    --gate-json) GATE_JSON="${2:-}"; shift 2 ;;
    -h|--help)
      sed -n '2,10p' "$0"
      exit 0
      ;;
    *) echo '{"verdict":"fail","error":"unknown argument"}' >&2; exit 2 ;;
  esac
done

if [[ "$VERDICT" != "merge-ready-green" && "$VERDICT" != "blocked" ]]; then
  echo '{"verdict":"fail","error":"--verdict merge-ready-green|blocked required"}' >&2
  exit 2
fi

if [[ "$VERDICT" == "blocked" && -z "$CAUSE" ]]; then
  echo '{"verdict":"fail","error":"--cause required when verdict is blocked"}' >&2
  exit 2
fi

if [[ -z "$PHASE" ]]; then
  PHASE="${SW_PHASE_SLUG:-}"
fi
if [[ -z "$PHASE" && -x "$ROOT/scripts/shipwright-state.sh" ]]; then
  PHASE="$(bash "$ROOT/scripts/shipwright-state.sh" read 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('phaseSlug',''))" 2>/dev/null || true)"
fi
PHASE="${PHASE:-unknown}"

if [[ -z "$HEAD" ]]; then
  HEAD="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo "")"
fi

if [[ "$VERDICT" == "merge-ready-green" && -z "$HEAD" ]]; then
  echo '{"verdict":"fail","error":"could not resolve HEAD for merge-ready-green"}' >&2
  exit 2
fi

if [[ -z "$OUT" ]]; then
  if [[ -n "${SW_RUN_DIR:-}" ]]; then
    OUT="${SW_RUN_DIR%/}/status.json"
  else
    OUT="$ROOT/.cursor/sw-deliver-runs/$PHASE/status.json"
  fi
fi

WRITE_ARGS=(--verdict "$VERDICT" --phase "$PHASE" --out "$OUT")
[[ -n "$HEAD" ]] && WRITE_ARGS+=(--head "$HEAD")
[[ -n "$PR" ]] && WRITE_ARGS+=(--pr "$PR")
[[ -n "$CAUSE" ]] && WRITE_ARGS+=(--cause "$CAUSE")
[[ -n "$GATE_JSON" && -f "$GATE_JSON" ]] && WRITE_ARGS+=(--gate-json "$GATE_JSON")
if [[ -n "$SHIP_STEPS_PATH" && -f "$SHIP_STEPS_PATH" ]]; then
  WRITE_ARGS+=(--ship-steps-path "$SHIP_STEPS_PATH")
fi

python3 "$ROOT/scripts/status_integrity.py" write "${WRITE_ARGS[@]}"

resolve_canonical_root() {
  if [[ -n "${SW_REPO_ROOT:-}" && -d "${SW_REPO_ROOT}" ]]; then
    cd "${SW_REPO_ROOT}" && pwd
    return 0
  fi
  local common=""
  common="$(git -C "$ROOT" rev-parse --git-common-dir 2>/dev/null || true)"
  if [[ -z "$common" || "$common" == ".git" ]]; then
    printf '%s\n' "$ROOT"
    return 0
  fi
  if [[ "$common" != /* ]]; then
    common="$(cd "$ROOT" && cd "$common" && pwd)"
  fi
  dirname "$common"
}

CANONICAL_ROOT="$(resolve_canonical_root 2>/dev/null || true)"
if [[ -n "$CANONICAL_ROOT" && -d "$CANONICAL_ROOT" ]]; then
  CANONICAL_OUT="${CANONICAL_ROOT%/}/.cursor/sw-deliver-runs/${PHASE}/status.json"
  OUT_ABS="$(cd "$(dirname "$OUT")" 2>/dev/null && pwd)/$(basename "$OUT")" || OUT_ABS="$OUT"
  CANONICAL_ABS="$(cd "$(dirname "$CANONICAL_OUT")" 2>/dev/null && pwd)/$(basename "$CANONICAL_OUT")" 2>/dev/null || CANONICAL_ABS="$CANONICAL_OUT"
  if [[ "$CANONICAL_ABS" != "$OUT_ABS" ]]; then
    mkdir -p "$(dirname "$CANONICAL_OUT")"
    cp -f "$OUT" "$CANONICAL_OUT"
    chmod 600 "$CANONICAL_OUT" 2>/dev/null || true
  fi
fi

if [[ "$VERDICT" == "blocked" ]]; then
  STATE_PATH="$(python3 "$ROOT/scripts/wave_state.py" "$ROOT" resolve state-path 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('path',''))" || true)"
  if [[ -n "$STATE_PATH" && -f "$STATE_PATH" ]]; then
    python3 "$ROOT/scripts/wave_state.py" "$ROOT" state phase --slug "$PHASE" --status blocked >/dev/null 2>&1 || true
  fi
fi
