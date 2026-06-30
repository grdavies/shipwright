#!/usr/bin/env bash
# Deterministic verification-gate verdict helper (IM1 / U1; hardened plan 005).
#
# Consumes structured evidence status files — not raw /tmp logs.
# Prints JSON verdict to stdout. Complementary to check-gate.py; never overrides CI truth.
#
# Exit codes:
#   0  verified
#  10  inconclusive
#  20  not-verified
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=evidence-read.py
source "$ROOT/scripts/evidence-read.py"

VERIFY_STATUS=""
GATE_JSON=""
REVIEW_STATUS=""
BASELINE_VERIFY=""
BASELINE_GATE=""
REQUIRE_GATE=0
PR_CONTEXT="auto"

usage() {
  echo "Usage: verify-evidence.py --verify-status PATH [--gate-json PATH] [--require-gate] [--pr-context on|off|auto] [--review-status PATH] [--baseline-verify PATH] [--baseline-gate PATH]" >&2
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --verify-status) VERIFY_STATUS="${2:-}"; shift 2 ;;
    --gate-json) GATE_JSON="${2:-}"; shift 2 ;;
    --require-gate) REQUIRE_GATE=1; shift ;;
    --pr-context) PR_CONTEXT="${2:-}"; shift 2 ;;
    --review-status) REVIEW_STATUS="${2:-}"; shift 2 ;;
    --baseline-verify) BASELINE_VERIFY="${2:-}"; shift 2 ;;
    --baseline-gate) BASELINE_GATE="${2:-}"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "unknown arg: $1" >&2; usage ;;
  esac
done

[[ -n "$VERIFY_STATUS" ]] || usage

case "$PR_CONTEXT" in
  on|off|auto) ;;
  *) echo "invalid --pr-context: $PR_CONTEXT" >&2; exit 2 ;;
esac

# --- helpers ------------------------------------------------------------------
jq_from_safe() {
  local path="$1" filter="$2"
  safe_read_check "$path" || return 1
  exec 3< "$path"
  jq -r "$filter" <&3
  local ec=$?
  exec 3<&-
  return $ec
}

read_verify_pass() {
  local f="$1"
  if [[ ! -f "$f" ]]; then
    echo "missing"
    return
  fi
  if ! safe_jq "$f" '.' >/dev/null 2>&1; then
    echo "invalid"
    return
  fi
  local ec status has_commands
  ec="$(jq_from_safe "$f" 'if .exitCode != null then .exitCode elif .overall.exitCode != null then .overall.exitCode else 1 end' 2>/dev/null || echo "1")"
  status="$(jq_from_safe "$f" 'if .status != null then .status elif .overall.status != null then .overall.status else "fail" end' 2>/dev/null || echo "fail")"
  has_commands="$(jq_from_safe "$f" 'if (.commands | type) == "array" and (.commands | length) > 0 then "yes" else "no" end' 2>/dev/null || echo "no")"
  if [[ "$has_commands" == "yes" ]]; then
    local failing_cmds
    failing_cmds="$(jq_from_safe "$f" '[.commands[] | select(.status != "pass" or (.exitCode != null and .exitCode != 0))] | length' 2>/dev/null || echo "1")"
    if [[ "$failing_cmds" != "0" ]]; then
      echo "fail"
      return
    fi
  fi
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
  if ! safe_jq "$f" '.' >/dev/null 2>&1; then
    echo "invalid"
    return
  fi
  local v
  v="$(jq_from_safe "$f" '.verdict // "red"' 2>/dev/null || echo "red")"
  if [[ "$v" == "green" ]]; then
    echo "pass"
  else
    echo "fail"
  fi
}

verify_fingerprint() {
  local f="$1"
  if safe_jq "$f" '(.commands | type) == "array" and (.commands | length) > 0' >/dev/null 2>&1; then
    jq_from_safe "$f" '[.commands[] | {name, status}] | sort_by(.name)' 2>/dev/null || echo '[]'
  else
    jq_from_safe "$f" '{exitCode: (if .exitCode != null then .exitCode elif .overall.exitCode != null then .overall.exitCode else 1 end), status: (if .status != null then .status elif .overall.status != null then .overall.status else "fail" end)}' 2>/dev/null || echo '{}'
  fi
}

verify_failing_names() {
  local f="$1"
  if safe_jq "$f" '(.commands | type) == "array" and (.commands | length) > 0' >/dev/null 2>&1; then
    jq_from_safe "$f" '[.commands[] | select(.status != "pass") | .name] | sort' 2>/dev/null || echo '[]'
  else
    echo 'null'
  fi
}

gate_fingerprint() {
  local f="$1"
  jq_from_safe "$f" '{verdict: (.verdict // "red"), failingChecks: (.failingChecks // [])}' 2>/dev/null || echo '{}'
}

has_new_verify_failure() {
  local head="$1" base="$2"
  local head_fail base_fail
  head_fail="$(verify_failing_names "$head")"
  base_fail="$(verify_failing_names "$base")"
  if [[ "$head_fail" != "null" && "$base_fail" != "null" ]]; then
    python3 - "$head_fail" "$base_fail" <<'PY'
import json, sys
head = set(json.loads(sys.argv[1]))
base = set(json.loads(sys.argv[2]))
# Exit 0 when head introduces a failing command not present at baseline.
sys.exit(0 if not head <= base else 1)
PY
    return $?
  fi
  [[ "$(verify_fingerprint "$head")" != "$(verify_fingerprint "$base")" ]]
}

detect_pr_context() {
  case "$PR_CONTEXT" in
    on) return 0 ;;
    off) return 1 ;;
  esac
  if [[ -n "${GITHUB_HEAD_REF:-}" || -n "${GITHUB_EVENT_PULL_REQUEST_NUMBER:-}" ]]; then
    return 0
  fi
  local pr_field
  pr_field="$("$ROOT/scripts/shipwright-state.py" read 2>/dev/null | jq -r '.pr.number // .prNumber // empty' 2>/dev/null || true)"
  if [[ -n "$pr_field" ]]; then
    return 0
  fi
  if git rev-parse --abbrev-ref '@{u}' >/dev/null 2>&1; then
    local counts ahead behind
    counts="$(git rev-list --left-right --count '@{u}'...HEAD 2>/dev/null || echo "0	0")"
    behind="${counts%%	*}"
    ahead="${counts##*	}"
    if [[ "${ahead:-0}" -gt 0 || "${behind:-0}" -gt 0 ]]; then
      return 0
    fi
  fi
  [[ -n "$GATE_JSON" ]] && return 0
  return 1
}

emit() {
  local verdict="$1" reason="$2" inconclusive_class="$3" verify_s="$4" gate_s="$5" review_s="$6" baseline_present="$7"
  local gate_req="not-required"
  if [[ "$REQUIRE_GATE" -eq 1 ]] || detect_pr_context; then
    gate_req="required"
  fi
  if [[ -n "$inconclusive_class" ]]; then
    jq -n \
      --arg verdict "$verdict" \
      --arg reason "$reason" \
      --arg ic "$inconclusive_class" \
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
        inconclusiveClass: $ic,
        evidence: {
          verify: {path: $vp, present: ($vs != "missing"), status: $vs},
          gate: {path: (if $gp == "" then null else $gp end), required: ($gr == "required"), present: ($gs != "missing" and $gs != "not-required"), status: $gs},
          review: {path: (if $rp == "" then null else $rp end), present: ($rs != "absent"), status: $rs},
          baseline: {present: $bp}
        }
      }'
  else
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
  fi
  case "$verdict" in
    verified) exit 0 ;;
    inconclusive) exit 10 ;;
    not-verified) exit 20 ;;
    *) exit 1 ;;
  esac
}

emit_inconclusive() {
  emit "inconclusive" "$1" "$2" "${3:-missing}" "${4:-not-required}" "${5:-absent}" "${6:-0}"
}

# --- evaluate required evidence -----------------------------------------------
if [[ -f "$VERIFY_STATUS" ]] && ! safe_read_check "$VERIFY_STATUS"; then
  emit_inconclusive "verify status rejected by safe_read" "missing-required" "invalid" "not-required" "absent" 0
fi

VERIFY_S="$(read_verify_pass "$VERIFY_STATUS")"

# --- unconfigured verify (R28/DL-13) -----------------------------------------
UNCONFIGURED_SCRIPT="$ROOT/scripts/verify-unconfigured.py"
if [[ -x "$UNCONFIGURED_SCRIPT" ]]; then
  UC_JSON="$(bash "$UNCONFIGURED_SCRIPT" --json 2>/dev/null || true)"
  UC_CONFIGURED="$(echo "$UC_JSON" | jq -r '.configured // true' 2>/dev/null || echo true)"
  UC_ALLOW="$(echo "$UC_JSON" | jq -r '.allowUnconfigured // false' 2>/dev/null || echo false)"
  UC_BLOCK=0
  if [[ "$UC_CONFIGURED" != "true" && "$UC_ALLOW" != "true" ]]; then
    UC_BLOCK=1
    if [[ "${SW_PHASE_MODE:-}" =~ ^(1|true|yes|TRUE|YES)$ ]]; then
      emit "not-verified" "verify-unconfigured — run /sw-init" "" "$VERIFY_S" "not-required" "absent" 0
    fi
    # Interactive/manual: non-blocking but loud — continue evaluation
  fi
fi

if [[ "$VERIFY_S" == "missing" ]]; then
  emit_inconclusive "required verify status missing" "missing-required" "$VERIFY_S" "not-required" "absent" 0
fi
if [[ "$VERIFY_S" == "invalid" ]]; then
  emit_inconclusive "verify status invalid JSON" "missing-required" "$VERIFY_S" "not-required" "absent" 0
fi

GATE_REQUIRED=0
if [[ "$REQUIRE_GATE" -eq 1 ]] || detect_pr_context; then
  GATE_REQUIRED=1
fi

GATE_S="not-required"
if [[ "$GATE_REQUIRED" -eq 1 || -n "$GATE_JSON" ]]; then
  local_gate="${GATE_JSON:-/nonexistent}"
  if [[ -f "$local_gate" ]] && ! safe_read_check "$local_gate"; then
    emit_inconclusive "gate JSON rejected by safe_read" "missing-required" "$VERIFY_S" "invalid" "absent" 0
  fi
  GATE_S="$(read_gate_pass "$local_gate")"
  if [[ "$GATE_S" == "missing" ]]; then
    emit_inconclusive "required gate JSON missing" "missing-required" "$VERIFY_S" "$GATE_S" "absent" 0
  fi
  if [[ "$GATE_S" == "invalid" ]]; then
    emit_inconclusive "gate JSON invalid" "missing-required" "$VERIFY_S" "$GATE_S" "absent" 0
  fi
fi

REVIEW_S="absent"
if [[ -n "$REVIEW_STATUS" ]]; then
  if [[ ! -f "$REVIEW_STATUS" ]]; then
    REVIEW_S="absent"
  else
    if ! safe_read_check "$REVIEW_STATUS"; then
      emit_inconclusive "review status rejected by safe_read" "missing-required" "$VERIFY_S" "$GATE_S" "absent" 0
    fi
    REVIEW_S="$(read_verify_pass "$REVIEW_STATUS")"
    if [[ "$REVIEW_S" == "invalid" ]]; then
      emit_inconclusive "review status invalid JSON" "missing-required" "$VERIFY_S" "$GATE_S" "$REVIEW_S" 0
    fi
  fi
fi

BASELINE_PRESENT=0
if [[ -n "$BASELINE_VERIFY" && -f "$BASELINE_VERIFY" ]]; then
  BASELINE_PRESENT=1
fi
if [[ -n "$BASELINE_GATE" && -f "$BASELINE_GATE" ]]; then
  BASELINE_PRESENT=1
fi

if [[ -n "$BASELINE_VERIFY" && ! -f "$BASELINE_VERIFY" ]]; then
  emit_inconclusive "baseline verify file missing" "missing-required" "$VERIFY_S" "$GATE_S" "$REVIEW_S" 0
fi
if [[ -n "$BASELINE_GATE" && ! -f "$BASELINE_GATE" ]]; then
  emit_inconclusive "baseline gate file missing" "missing-required" "$VERIFY_S" "$GATE_S" "$REVIEW_S" 0
fi

if [[ -n "$BASELINE_VERIFY" && -f "$BASELINE_VERIFY" ]] && ! safe_read_check "$BASELINE_VERIFY"; then
  emit_inconclusive "baseline verify rejected by safe_read" "missing-required" "$VERIFY_S" "$GATE_S" "$REVIEW_S" 1
fi
if [[ -n "$BASELINE_GATE" && -f "$BASELINE_GATE" ]] && ! safe_read_check "$BASELINE_GATE"; then
  emit_inconclusive "baseline gate rejected by safe_read" "missing-required" "$VERIFY_S" "$GATE_S" "$REVIEW_S" 1
fi

# --- head all passing ---------------------------------------------------------
HEAD_FAIL=0
[[ "$VERIFY_S" == "fail" ]] && HEAD_FAIL=1
[[ "$GATE_S" == "fail" ]] && HEAD_FAIL=1
[[ "$REVIEW_S" == "fail" ]] && HEAD_FAIL=1

if [[ "$HEAD_FAIL" -eq 0 ]]; then
  emit "verified" "all required evidence passing" "" "$VERIFY_S" "$GATE_S" "$REVIEW_S" "$BASELINE_PRESENT"
fi

# --- head has failures --------------------------------------------------------
if [[ "$BASELINE_PRESENT" -eq 0 ]]; then
  emit_inconclusive "head has failures but no baseline for attribution" "no-baseline" "$VERIFY_S" "$GATE_S" "$REVIEW_S" 0
fi

if [[ "$VERIFY_S" == "fail" && ( -z "$BASELINE_VERIFY" || ! -f "$BASELINE_VERIFY" ) ]]; then
  emit_inconclusive "verify failure without baseline for attribution" "no-baseline" "$VERIFY_S" "$GATE_S" "$REVIEW_S" "$BASELINE_PRESENT"
fi
if [[ "$GATE_S" == "fail" && ( -z "$BASELINE_GATE" || ! -f "$BASELINE_GATE" ) ]]; then
  emit_inconclusive "gate failure without baseline for attribution" "no-baseline" "$VERIFY_S" "$GATE_S" "$REVIEW_S" "$BASELINE_PRESENT"
fi
if [[ "$REVIEW_S" == "fail" ]]; then
  emit_inconclusive "review failure without baseline for attribution" "no-baseline" "$VERIFY_S" "$GATE_S" "$REVIEW_S" "$BASELINE_PRESENT"
fi

NEW_FAILURE=0

if [[ "$VERIFY_S" == "fail" && -n "$BASELINE_VERIFY" && -f "$BASELINE_VERIFY" ]]; then
  BASE_V="$(read_verify_pass "$BASELINE_VERIFY")"
  if [[ "$BASE_V" == "pass" ]]; then
    NEW_FAILURE=1
  elif has_new_verify_failure "$VERIFY_STATUS" "$BASELINE_VERIFY"; then
    NEW_FAILURE=1
  fi
elif [[ "$VERIFY_S" == "fail" && -z "$BASELINE_VERIFY" ]]; then
  :
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
  emit "not-verified" "fresh attributable failure vs baseline" "" "$VERIFY_S" "$GATE_S" "$REVIEW_S" 1
fi

emit_inconclusive "pre-existing unchanged failure or unattributed dimension" "unattributed" "$VERIFY_S" "$GATE_S" "$REVIEW_S" 1
