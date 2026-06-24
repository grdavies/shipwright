#!/usr/bin/env bash
# Untrusted-output validation before auto-applying local review fixes.
#
# Usage: code-review-apply-check.sh --finding PATH --repo-root PATH [--max-fix-chars N]
# Exit: 0 eligible, 20 reject (surface only)
set -euo pipefail

FINDING=""
REPO_ROOT="${PWD}"
MAX_FIX_CHARS=2000

usage() {
  echo "Usage: code-review-apply-check.sh --finding JSON --repo-root PATH [--max-fix-chars N]" >&2
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --finding) FINDING="${2:-}"; shift 2 ;;
    --repo-root) REPO_ROOT="${2:-}"; shift 2 ;;
    --max-fix-chars) MAX_FIX_CHARS="${2:-}"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "unknown arg: $1" >&2; usage ;;
  esac
done

[[ -n "$FINDING" ]] || usage

if ! jq -e . <<<"$FINDING" >/dev/null 2>&1; then
  jq -n '{eligible:false,reason:"malformed finding JSON"}'
  exit 20
fi

sev="$(jq -r '.severity // "P3"' <<<"$FINDING")"
if [[ "$sev" == "P0" || "$sev" == "P1" ]]; then
  jq -n --arg s "$sev" '{eligible:false,reason:"P0/P1 never auto-applied",severity:$s}'
  exit 20
fi

if [[ "$sev" != "P2" && "$sev" != "P3" ]]; then
  jq -n '{eligible:false,reason:"severity not P2/P3"}'
  exit 20
fi

fix="$(jq -r '.suggested_fix // ""' <<<"$FINDING")"
if [[ -z "$fix" || "$fix" == "null" ]]; then
  jq -n '{eligible:false,reason:"no concrete suggested_fix"}'
  exit 20
fi

reqv="$(jq -r 'if .requires_verification == null then true else .requires_verification end' <<<"$FINDING")"
if [[ "$reqv" == "true" ]]; then
  jq -n '{eligible:false,reason:"requires_verification is true"}'
  exit 20
fi

if [[ "${#fix}" -gt "$MAX_FIX_CHARS" ]]; then
  jq -n --argjson n "$MAX_FIX_CHARS" '{eligible:false,reason:"fix exceeds size bound",max_chars:$n}'
  exit 20
fi

file="$(jq -r '.file // ""' <<<"$FINDING")"
if [[ -z "$file" || "$file" == "null" ]]; then
  jq -n '{eligible:false,reason:"missing file path"}'
  exit 20
fi

if [[ "$file" == /* ]]; then
  jq -n '{eligible:false,reason:"absolute file path rejected"}'
  exit 20
fi

if echo "$file" | grep -qE '\.\.|^/'; then
  jq -n '{eligible:false,reason:"path traversal rejected"}'
  exit 20
fi

resolved="$(python3 -c "
import os, sys
root = os.path.realpath(sys.argv[1])
target = os.path.realpath(os.path.join(root, sys.argv[2]))
print(target)
" "$REPO_ROOT" "$file" 2>/dev/null || true)"
repo_real="$(python3 -c "import os; print(os.path.realpath('$REPO_ROOT'))" 2>/dev/null || true)"
if [[ -z "$resolved" || -z "$repo_real" ]]; then
  jq -n '{eligible:false,reason:"could not resolve file path"}'
  exit 20
fi
if [[ "$resolved" != "$repo_real" && "$resolved" != "$repo_real"/* ]]; then
  jq -n --arg f "$file" '{eligible:false,reason:"file outside repo root",file:$f}'
  exit 20
fi

# Security-sensitive surfaces — never auto-apply.
lower_file="$(echo "$file" | tr '[:upper:]' '[:lower:]')"
if echo "$lower_file" | grep -qE '(^|/)(auth|secret|credential|\.env|\.github/workflows/)|/ci/|check-gate'; then
  jq -n --arg f "$file" '{eligible:false,reason:"security-sensitive target",file:$f}'
  exit 20
fi

jq -n --arg f "$file" --arg s "$sev" '{eligible:true,file:$f,severity:$s}'
exit 0
