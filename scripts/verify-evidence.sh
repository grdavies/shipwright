#!/usr/bin/env bash
# Deterministic verification-gate verdict helper (IM1 / U1).
#
# Consumes structured evidence status files — not raw /tmp logs.
# Prints JSON verdict to stdout. Complementary to check-gate.sh; never overrides CI truth.
#
# Exit codes:
#   0  verified
#  10  inconclusive
#  20  not-verified
set -euo pipefail

VERIFY_STATUS=""
GATE_JSON=""
REVIEW_STATUS=""
BASELINE_VERIFY=""
BASELINE_GATE=""
REQUIRE_GATE=0

usage() {
  echo "Usage: verify-evidence.sh --verify-status PATH [--gate-json PATH] [--require-gate] [--review-status PATH] [--baseline-verify PATH] [--baseline-gate PATH]" >&2
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --verify-status) VERIFY_STATUS="${2:-}"; shift 2 ;;
    --gate-json) GATE_JSON="${2:-}"; shift 2 ;;
    --require-gate) REQUIRE_GATE=1; shift ;;
    --review-status) REVIEW_STATUS="${2:-}"; shift 2 ;;
    --baseline-verify) BASELINE_VERIFY="${2:-}"; shift 2 ;;
    --baseline-gate) BASELINE_GATE="${2:-}"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "unknown arg: $1" >&2; usage ;;
  esac
done

[[ -n "$VERIFY_STATUS" ]] || usage

# --- helpers ------------------------------------------------------------------
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

read_gate_pass() {
  local f="$1"
  if [[ ! -f "$f" ]]; then
    echo "missing"
    return
  fi
  if ! jq -e . "$f" >/dev/null 2>&1; then
    echo "invalid"
    return
  fi
  local v
  v="$(jq -r '.verdict // "red"' "$f")"
  if [[ "$v" == "green" ]]; then
    echo "pass"
  else
    echo "fail"
  fi
}

verify_fingerprint() {
  local f="$1"
  jq -c '{exitCode: (if .exitCode != null then .exitCode elif .overall.exitCode != null then .overall.exitCode else 1 end), status: (if .status != null then .status elif .overall.status != null then .overall.status else "fail" end)}' "$f" 2>/dev/null || echo '{}'
}

gate_fingerprint() {
  local f="$1"
  jq -c '{verdict: (.verdict // "red"), failingChecks: (.failingChecks // [])}' "$f" 2>/dev/null || echo '{}'
}

emit() {
  local verdict="$1" reason="$2" verify_s="$3" gate_s="$4" review_s="$5" baseline_present="$6"
  local gate_req="not-required"
  [[ "$REQUIRE_GATE" -eq 1 ]] && gate_req="required"
  jq -n \
    --arg verdict "$verdict" \
    --arg reason "$reason" \
    --arg vp "${VERIFY_STATUS:-}" \
    --arg gp "${GATE_JSON:-}" \
    --arg rp "${REVIEW_STATUS:-}" \
    --arg vs "$verify_s" \
    --arg gs "$gate_s" \
    --arg rs "$review_s" \
    --argjson bp "$baseline_present" \
    --arg gr "$gate_req" \
    '{
      verdict: $verdict,
      reason: $reason,
      evidence: {
        verify: {path: $vp, present: ($vs != "missing"), status: $vs},
        gate: {path: (if $gp == "" then null else $gp end), required: ($gr == "required"), present: ($gs != "missing" and $gs != "not-required"), status: $gs},
        review: {path: (if $rp == "" then null else $rp end), present: ($rs != "absent"), status: $rs},
        baseline: {present: $bp}
      }
    }'
  case "$verdict" in
    verified) exit 0 ;;
    inconclusive) exit 10 ;;
    not-verified) exit 20 ;;
    *) exit 1 ;;
  esac
}

# --- evaluate required evidence -----------------------------------------------
VERIFY_S="$(read_verify_pass "$VERIFY_STATUS")"

if [[ "$VERIFY_S" == "missing" ]]; then
  emit "inconclusive" "required verify status missing" "$VERIFY_S" "not-required" "absent" 0
fi
if [[ "$VERIFY_S" == "invalid" ]]; then
  emit "inconclusive" "verify status invalid JSON" "$VERIFY_S" "not-required" "absent" 0
fi

GATE_S="not-required"
if [[ "$REQUIRE_GATE" -eq 1 || -n "$GATE_JSON" ]]; then
  GATE_S="$(read_gate_pass "${GATE_JSON:-/nonexistent}")"
  if [[ "$GATE_S" == "missing" ]]; then
    emit "inconclusive" "required gate JSON missing" "$VERIFY_S" "$GATE_S" "absent" 0
  fi
  if [[ "$GATE_S" == "invalid" ]]; then
    emit "inconclusive" "gate JSON invalid" "$VERIFY_S" "$GATE_S" "absent" 0
  fi
fi

REVIEW_S="absent"
if [[ -n "$REVIEW_STATUS" ]]; then
  if [[ ! -f "$REVIEW_STATUS" ]]; then
    REVIEW_S="absent"
  else
    REVIEW_S="$(read_verify_pass "$REVIEW_STATUS")"
    if [[ "$REVIEW_S" == "invalid" ]]; then
      emit "inconclusive" "review status invalid JSON" "$VERIFY_S" "$GATE_S" "$REVIEW_S" 0
    fi
  fi
fi

BASELINE_PRESENT=0
[[ -n "$BASELINE_VERIFY" || -n "$BASELINE_GATE" ]] && BASELINE_PRESENT=1

# --- head all passing ---------------------------------------------------------
HEAD_FAIL=0
[[ "$VERIFY_S" == "fail" ]] && HEAD_FAIL=1
[[ "$GATE_S" == "fail" ]] && HEAD_FAIL=1
[[ "$REVIEW_S" == "fail" ]] && HEAD_FAIL=1

if [[ "$HEAD_FAIL" -eq 0 ]]; then
  emit "verified" "all required evidence passing" "$VERIFY_S" "$GATE_S" "$REVIEW_S" "$BASELINE_PRESENT"
fi

# --- head has failures --------------------------------------------------------
if [[ "$BASELINE_PRESENT" -eq 0 ]]; then
  emit "inconclusive" "head has failures but no baseline for attribution" "$VERIFY_S" "$GATE_S" "$REVIEW_S" 0
fi

NEW_FAILURE=0

if [[ "$VERIFY_S" == "fail" && -n "$BASELINE_VERIFY" && -f "$BASELINE_VERIFY" ]]; then
  BASE_V="$(read_verify_pass "$BASELINE_VERIFY")"
  if [[ "$BASE_V" == "pass" ]]; then
    NEW_FAILURE=1
  elif [[ "$(verify_fingerprint "$VERIFY_STATUS")" != "$(verify_fingerprint "$BASELINE_VERIFY")" ]]; then
    NEW_FAILURE=1
  fi
elif [[ "$VERIFY_S" == "fail" && -z "$BASELINE_VERIFY" ]]; then
  : # cannot attribute verify failure without baseline
fi

if [[ "$GATE_S" == "fail" && -n "$BASELINE_GATE" && -f "$BASELINE_GATE" ]]; then
  BASE_G="$(read_gate_pass "$BASELINE_GATE")"
  if [[ "$BASE_G" == "pass" ]]; then
    NEW_FAILURE=1
  elif [[ "$(gate_fingerprint "$GATE_JSON")" != "$(gate_fingerprint "$BASELINE_GATE")" ]]; then
    NEW_FAILURE=1
  fi
fi

if [[ "$NEW_FAILURE" -eq 1 ]]; then
  emit "not-verified" "fresh attributable failure vs baseline" "$VERIFY_S" "$GATE_S" "$REVIEW_S" 1
fi

emit "inconclusive" "pre-existing unchanged failure or unattributed dimension" "$VERIFY_S" "$GATE_S" "$REVIEW_S" 1
