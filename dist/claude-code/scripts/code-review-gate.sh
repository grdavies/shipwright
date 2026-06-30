#!/usr/bin/env bash
# Severity gate for local code-review normalized output.
#
# Usage: code-review-gate.py --input PATH --gate-config PATH
# Exit: 0 continue, 20 halt (validated P0/P1 in halting mode)
set -euo pipefail

INPUT=""
GATE_CONFIG=""

usage() {
  echo "Usage: code-review-gate.py --input PATH --gate-config PATH" >&2
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --input) INPUT="${2:-}"; shift 2 ;;
    --gate-config) GATE_CONFIG="${2:-}"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "unknown arg: $1" >&2; usage ;;
  esac
done

[[ -n "$INPUT" && -n "$GATE_CONFIG" ]] || usage
[[ -f "$INPUT" ]] || { jq -n '{verdict:"skip",reason:"missing normalized input"}'; exit 0; }
[[ -f "$GATE_CONFIG" ]] || { jq -n '{verdict:"skip",reason:"missing gate config"}'; exit 0; }

HALT_ON="$(jq -c '.haltOn // []' "$GATE_CONFIG")"
SURFACE="$(jq -c '.surface // ["P0","P1","P2","P3"]' "$GATE_CONFIG")"

STATUS="$(jq -r '.status // "failed"' "$INPUT")"
if [[ "$STATUS" != "complete" ]]; then
  REASON="$(jq -r '.reason // "non-complete local review"' "$INPUT")"
  jq -n --arg st "$STATUS" --arg r "$REASON" \
    '{verdict:"skip",status:$st,reason:$r,halt:false,surfaced:[]}'
  exit 0
fi

SURFACED='[]'
HALT=false
HALT_FINDINGS='[]'

while IFS= read -r row; do
  [[ -n "$row" ]] || continue
  sev="$(jq -r '.severity // "P3"' <<<"$row")"
  on_surface="$(jq -e --arg s "$sev" '(. // []) | index($s) != null' <<<"$SURFACE" >/dev/null 2>&1 && echo yes || echo no)"
  on_halt="$(jq -e --arg s "$sev" '(. // []) | index($s) != null' <<<"$HALT_ON" >/dev/null 2>&1 && echo yes || echo no)"
  if [[ "$on_surface" == "yes" ]]; then
    SURFACED="$(jq --argjson r "$row" '. + [$r]' <<<"$SURFACED")"
  fi
  if [[ "$on_halt" == "yes" ]]; then
    HALT=true
    HALT_FINDINGS="$(jq --argjson r "$row" '. + [$r]' <<<"$HALT_FINDINGS")"
  fi
done < <(jq -c '.findings[]?' "$INPUT" 2>/dev/null || true)

if [[ "$HALT" == "true" ]]; then
  jq -n --argjson surfaced "$SURFACED" --argjson halt_findings "$HALT_FINDINGS" \
    '{verdict:"halt",halt:true,surfaced:$surfaced,halt_findings:$halt_findings}'
  exit 20
fi

jq -n --argjson surfaced "$SURFACED" \
  '{verdict:"continue",halt:false,surfaced:$surfaced}'
exit 0
