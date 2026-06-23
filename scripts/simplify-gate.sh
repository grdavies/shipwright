#!/usr/bin/env bash
# Behavior-preservation gate after /pf-simplify (IM7 / U8).
# Compares pre-simplify vs post-simplify verify status files.
#
# Exit codes:
#   0  preserved
#  10  inconclusive
#  20  regressed
set -euo pipefail

BASELINE=""
POST=""

usage() {
  echo "Usage: simplify-gate.sh --baseline-verify PATH --post-verify PATH" >&2
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --baseline-verify) BASELINE="${2:-}"; shift 2 ;;
    --post-verify) POST="${2:-}"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "unknown arg: $1" >&2; usage ;;
  esac
done

[[ -n "$BASELINE" && -n "$POST" ]] || usage

read_verify_pass() {
  local f="$1"
  if [[ ! -f "$f" ]]; then
    echo "missing"
    return
  fi
  if ! jq -e . "$f" >/dev/null 2>&1; then
    echo "invalid"
    return
  fi
  local ec status
  ec="$(jq -r 'if .exitCode != null then .exitCode elif .overall.exitCode != null then .overall.exitCode else 1 end' "$f")"
  status="$(jq -r 'if .status != null then .status elif .overall.status != null then .overall.status else "fail" end' "$f")"
  if [[ "$ec" == "0" && "$status" == "pass" ]]; then
    echo "pass"
  else
    echo "fail"
  fi
}

BASE_STATE=$(read_verify_pass "$BASELINE")
POST_STATE=$(read_verify_pass "$POST")

if [[ "$BASE_STATE" == "missing" || "$POST_STATE" == "missing" || "$BASE_STATE" == "invalid" || "$POST_STATE" == "invalid" ]]; then
  jq -n --arg b "$BASE_STATE" --arg p "$POST_STATE" \
    '{verdict:"inconclusive",reason:"missing or invalid verify status",baseline:$b,post:$p}'
  exit 10
fi

if [[ "$BASE_STATE" != "pass" ]]; then
  jq -n --arg b "$BASE_STATE" --arg p "$POST_STATE" \
    '{verdict:"inconclusive",reason:"baseline verify was not passing",baseline:$b,post:$p}'
  exit 10
fi

if [[ "$POST_STATE" == "pass" ]]; then
  jq -n --arg b "$BASELINE" --arg p "$POST" \
    '{verdict:"preserved",baseline:$b,post:$p}'
  exit 0
fi

jq -n --arg b "$BASELINE" --arg p "$POST" \
  '{verdict:"regressed",reason:"post-simplify verify failed",baseline:$b,post:$p}'
exit 20
