#!/usr/bin/env bash
# Normalize ce-code-review mode:agent JSON to providers/code-review/CAPABILITIES.md contract.
#
# Usage: code-review-normalize.py --input PATH [--repo-root PATH]
# Exit 0 on success; 1 on malformed input (emits fail-closed skip JSON on stdout).
set -euo pipefail

INPUT=""
REPO_ROOT="${PWD}"

usage() {
  echo "Usage: code-review-normalize.py --input PATH [--repo-root PATH]" >&2
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --input) INPUT="${2:-}"; shift 2 ;;
    --repo-root) REPO_ROOT="${2:-}"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "unknown arg: $1" >&2; usage ;;
  esac
done

[[ -n "$INPUT" ]] || usage

emit_skip() {
  local status="$1" reason="$2"
  jq -n --arg st "$status" --arg r "$reason" \
    '{status:$st, verdict:"not-ready", reason:$r, findings:[]}'
  exit 0
}

if [[ ! -f "$INPUT" ]]; then
  emit_skip "failed" "input file missing"
fi

if ! jq -e . "$INPUT" >/dev/null 2>&1; then
  emit_skip "failed" "malformed JSON from ce-code-review adapter"
fi

CE_STATUS="$(jq -r '.status // "failed"' "$INPUT")"
CE_REASON="$(jq -r '.reason // ""' "$INPUT")"

case "$CE_STATUS" in
  skipped|failed|degraded)
    emit_skip "$CE_STATUS" "${CE_REASON:-non-finding outcome from ce-code-review}"
    ;;
  complete)
    ;;
  *)
    emit_skip "failed" "unknown ce-code-review status: $CE_STATUS"
    ;;
esac

map_verdict() {
  case "$1" in
    "Ready to merge") echo "ready" ;;
    "Ready with fixes") echo "ready-with-fixes" ;;
    "Not ready") echo "not-ready" ;;
    ready|ready-with-fixes|not-ready) echo "$1" ;;
    *) echo "not-ready" ;;
  esac
}

is_requirement_stage_finding() {
  local title reviewers why
  title="$(jq -r '.title // ""' <<<"$1")"
  reviewers="$(jq -r '(.reviewers // []) | join(" ")' <<<"$1")"
  why="$(jq -r '.why_it_matters // ""' <<<"$1")"
  local blob="${title} ${reviewers} ${why}"
  if echo "$blob" | grep -qiE 'unaddressed requirement|implementation unit|requirements completeness|requirements trace|plan completeness'; then
    return 0
  fi
  if echo "$title" | grep -qiE '\bR[0-9]+\b.*(unaddressed|missing|not implemented)'; then
    return 0
  fi
  if echo "$reviewers" | grep -qi 'requirements'; then
    return 0
  fi
  return 1
}

CE_VERDICT="$(jq -r '.verdict // "Not ready"' "$INPUT")"
NORM_VERDICT="$(map_verdict "$CE_VERDICT")"

# Prefer actionable_findings when present; else findings array.
SOURCE_ARRAY="findings"
if jq -e '.actionable_findings | length > 0' "$INPUT" >/dev/null 2>&1; then
  SOURCE_ARRAY="actionable_findings"
fi

FILTERED='[]'
while IFS= read -r row; do
  [[ -n "$row" ]] || continue
  if is_requirement_stage_finding "$row"; then
    continue
  fi
  sev="$(jq -r '.severity // "P3"' <<<"$row")"
  file="$(jq -r '.file // ""' <<<"$row")"
  line="$(jq -r 'if .line != null then .line else 0 end' <<<"$row")"
  title="$(jq -r '.title // ""' <<<"$row")"
  fix="$(jq -r '.suggested_fix // ""' <<<"$row")"
  conf="$(jq -r 'if .confidence != null then .confidence else 0 end' <<<"$row")"
  reqv="$(jq -r 'if .requires_verification != null then .requires_verification else true end' <<<"$row")"
  norm_row="$(jq -n \
    --arg sev "$sev" --arg file "$file" --argjson line "$line" \
    --arg title "$title" --arg fix "$fix" --argjson conf "$conf" \
    --argjson reqv "$reqv" \
    '{severity:$sev,file:$file,line:$line,title:$title,suggested_fix:$fix,confidence:$conf,requires_verification:$reqv}')"
  FILTERED="$(jq --argjson r "$norm_row" '. + [$r]' <<<"$FILTERED")"
done < <(jq -c ".${SOURCE_ARRAY}[]?" "$INPUT" 2>/dev/null || true)

jq -n \
  --arg status "complete" \
  --arg verdict "$NORM_VERDICT" \
  --argjson findings "$FILTERED" \
  '{status:$status, verdict:$verdict, findings:$findings}'
