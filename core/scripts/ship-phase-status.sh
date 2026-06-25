#!/usr/bin/env bash
# Write durable /sw-ship phase-mode terminal status for /sw-deliver (R48/R18/R47).
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

if [[ -z "$OUT" ]]; then
  if [[ -n "${SW_RUN_DIR:-}" ]]; then
    OUT="${SW_RUN_DIR%/}/status.json"
  else
    OUT="$ROOT/.cursor/sw-deliver-runs/$PHASE/status.json"
  fi
fi

mkdir -p "$(dirname "$OUT")"

GATE_OBJ="null"
if [[ -n "$GATE_JSON" && -f "$GATE_JSON" ]]; then
  GATE_OBJ="$(python3 -c "import json; print(json.dumps(json.load(open('$GATE_JSON'))))")"
fi

PR_JSON="null"
if [[ -n "$PR" ]]; then
  PR_JSON="$PR"
fi

export VERDICT CAUSE PHASE HEAD OUT PR_JSON GATE_OBJ
python3 - <<'PY'
import json, os
from datetime import datetime, timezone

verdict = os.environ["VERDICT"]
cause = os.environ.get("CAUSE", "")
phase = os.environ["PHASE"]
head = os.environ.get("HEAD", "")
out = os.environ["OUT"]
pr = json.loads(os.environ["PR_JSON"])
gate = json.loads(os.environ["GATE_OBJ"])

doc = {
    "verdict": verdict,
    "phase": phase,
    "phaseMode": True,
    "head": head or None,
    "pr": pr,
    "gate": gate,
    "writtenAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
}
if verdict == "blocked":
    doc["cause"] = cause

text = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
with open(out, "w", encoding="utf-8") as f:
    f.write(text)
os.chmod(out, 0o600)
print(text, end="")
PY

if [[ "$VERDICT" == "blocked" && -f "$ROOT/.cursor/sw-deliver-state.json" ]]; then
  python3 "$ROOT/scripts/wave_state.py" "$ROOT" state phase --slug "$PHASE" --status blocked >/dev/null 2>&1 || true
fi
