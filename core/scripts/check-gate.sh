#!/usr/bin/env bash
# Deterministic phase-flow v2 CI readiness gate.
#
# Prints a single JSON verdict to stdout and never mutates anything. Canonical computation behind the
# `checks-gate` skill — `/pf-watch-ci` and stabilize invoke it instead of ad-hoc `gh` calls.
#
# Per-head review state comes from providers/review/<provider>.sh (executable adapter seam).
#
# Usage: check-gate.sh [PR_NUMBER]
# Config: .cursor/workflow.config.json or workflow.config.json
# Env: PF_GATE_NOW — unix seconds override for deterministic tests (grace window)
set -uo pipefail

CHECKS="$(mktemp "${TMPDIR:-/tmp}/pf-gate-checks.XXXXXX")"
ISSUE_COMMENTS="$(mktemp "${TMPDIR:-/tmp}/pf-gate-comments.XXXXXX")"
trap 'rm -f "$CHECKS" "$ISSUE_COMMENTS"' EXIT

# --- repo + config ------------------------------------------------------------
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
# shellcheck source=pf-resolve-plugin-root.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/pf-resolve-plugin-root.sh"
PLUGIN_ROOT="$(pf_resolve_plugin_root "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)")"
CONFIG=""
for p in "$ROOT/.cursor/workflow.config.json" "$ROOT/workflow.config.json"; do
  [ -f "$p" ] && CONFIG="$p" && break
done
cfg() {
  if [ -n "$CONFIG" ]; then jq -r "$1 // \"$2\"" "$CONFIG" 2>/dev/null || echo "$2"; else echo "$2"; fi
}
NEUTRAL_PASS="$(cfg '.checks.treatNeutralAsPass' 'true')"
GRACE_MIN="$(cfg '.coderabbit.reviewGraceMinutes' '15')"
REVIEW_PROVIDER="$(cfg '.review.provider' 'coderabbit')"
case "$REVIEW_PROVIDER" in
  [a-z0-9-]*) ;;
  *)
    echo "{\"verdict\":\"blocked\",\"reason\":\"invalid review.provider: $REVIEW_PROVIDER\"}"
    exit 30
    ;;
esac
ALLOW_JSON='[]'
[ -n "$CONFIG" ] && ALLOW_JSON="$(jq -c '.checks.neutralAllowlist // []' "$CONFIG" 2>/dev/null || echo '[]')"

# --- resolve PR + head --------------------------------------------------------
PR="${1:-}"
[ -z "$PR" ] && PR="$(gh pr view --json number --jq .number 2>/dev/null || true)"
if [ -z "$PR" ]; then
  echo '{"verdict":"blocked","reason":"no open PR for current branch"}'
  exit 30
fi
HEAD_SHA="$(gh pr view "$PR" --json headRefOid --jq .headRefOid 2>/dev/null || true)"
OWNER_REPO="$(gh repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null || true)"
if [ -z "$HEAD_SHA" ] || [ -z "$OWNER_REPO" ]; then
  echo '{"verdict":"blocked","reason":"incomplete GitHub metadata (head or repo)"}'
  exit 30
fi
OWNER="${OWNER_REPO%/*}"
REPO="${OWNER_REPO#*/}"

# --- checks -------------------------------------------------------------------
gh pr checks "$PR" --json name,state,bucket,link,workflow > "$CHECKS" 2>/dev/null || true
[ -s "$CHECKS" ] || echo '[]' > "$CHECKS"

CLASSIFIED="$(jq -c --argjson allow "$ALLOW_JSON" --argjson npass "$NEUTRAL_PASS" '
  def klass:
    .state as $s |
    if   ($s=="SUCCESS" or $s=="SKIPPED") then "pass"
    elif ($s=="NEUTRAL") then (if ($npass or (.name as $n | $allow|index($n))) then "pass" else "block" end)
    elif ($s|IN("PENDING","QUEUED","IN_PROGRESS","REQUESTED","WAITING","EXPECTED")) then "pending"
    else "fail" end;
  [ .[] | {name, state, class: klass} ]
' "$CHECKS" 2>/dev/null || echo '[]')"

FAILING="$(jq -c '[.[]|select(.class=="fail")|.name]' <<<"$CLASSIFIED")"
PENDING="$(jq -c '[.[]|select(.class=="pending")|.name]' <<<"$CLASSIFIED")"
BLOCKING="$(jq -c '[.[]|select(.class=="block")|.name]' <<<"$CLASSIFIED")"
CHECK_COUNT="$(jq 'length' <<<"$CLASSIFIED")"

# --- unresolved review threads ------------------------------------------------
UNRESOLVED=0
ACTIONABLE=0
CURSOR=""
if [ -n "$OWNER" ] && [ -n "$REPO" ]; then
  while :; do
    RESP="$(gh api graphql -f query='query($o:String!,$r:String!,$p:Int!,$c:String){repository(owner:$o,name:$r){pullRequest(number:$p){reviewThreads(first:100,after:$c){pageInfo{hasNextPage endCursor} nodes{isResolved isOutdated}}}}}' \
      -F o="$OWNER" -F r="$REPO" -F p="$PR" -F c="${CURSOR:-}" 2>/dev/null || echo '{}')"
    N="$(jq '[.data.repository.pullRequest.reviewThreads.nodes[]?|select(.isResolved==false)]|length' <<<"$RESP" 2>/dev/null || echo 0)"
    A="$(jq '[.data.repository.pullRequest.reviewThreads.nodes[]?|select(.isResolved==false and .isOutdated==false)]|length' <<<"$RESP" 2>/dev/null || echo 0)"
    UNRESOLVED=$((UNRESOLVED + N))
    ACTIONABLE=$((ACTIONABLE + A))
    HASNEXT="$(jq -r '.data.repository.pullRequest.reviewThreads.pageInfo.hasNextPage // false' <<<"$RESP" 2>/dev/null || echo false)"
    CURSOR="$(jq -r '.data.repository.pullRequest.reviewThreads.pageInfo.endCursor // empty' <<<"$RESP" 2>/dev/null || echo "")"
    [ "$HASNEXT" = "true" ] && [ -n "$CURSOR" ] || break
  done
fi

# --- review per-head state (executable adapter seam) --------------------------
# Opt-out: review.provider="none" or review.enabled=false disables review gating.
REVIEW_ENABLED="$(cfg '.review.enabled' 'true')"
if [ "$REVIEW_PROVIDER" = "none" ] || [ "$REVIEW_ENABLED" = "false" ]; then
  HAS_PER_HEAD=true
  CR_STATE="disabled"; CR_LANDED=true
  CR_REVIEWED_HEAD=""; CR_STATUS="disabled"
  CR_MARKER=0; CR_SKIP=0; MINS_SINCE=0
else
  ADAPTER="$PLUGIN_ROOT/providers/review/${REVIEW_PROVIDER}.sh"
  if [ ! -f "$ADAPTER" ]; then
    echo "{\"verdict\":\"blocked\",\"reason\":\"unknown review provider: $REVIEW_PROVIDER\"}"
    exit 30
  fi
  export PF_PR="$PR" PF_HEAD_SHA="$HEAD_SHA" PF_OWNER="$OWNER" PF_REPO="$REPO"
  export PF_OWNER_REPO="$OWNER_REPO" PF_CHECKS_FILE="$CHECKS" PF_ISSUE_COMMENTS_FILE="$ISSUE_COMMENTS"
  export PF_GRACE_MIN="$GRACE_MIN"
  REVIEW_JSON="$(bash "$ADAPTER")"
  HAS_PER_HEAD="$(echo "$REVIEW_JSON" | jq -r '.capabilities.perHeadState // false')"
  CR_STATE="$(echo "$REVIEW_JSON" | jq -r '.perHeadState // "in-flight"')"
  CR_LANDED="$(echo "$REVIEW_JSON" | jq -r '.perHeadLanded // false')"
  CR_REVIEWED_HEAD="$(echo "$REVIEW_JSON" | jq -r '.reviewedHead // ""')"
  CR_STATUS="$(echo "$REVIEW_JSON" | jq -r '.statusContext // "absent"')"
  CR_MARKER="$(echo "$REVIEW_JSON" | jq -r 'if .inProgressMarker then 1 else 0 end')"
  CR_SKIP="$(echo "$REVIEW_JSON" | jq -r 'if .skipped then 1 else 0 end')"
  MINS_SINCE="$(echo "$REVIEW_JSON" | jq -r '.minutesSinceHeadPush // 0')"
  if [ "$HAS_PER_HEAD" != "true" ]; then
    CR_STATE="in-flight"
    CR_LANDED=false
  fi
fi

# --- verdict ------------------------------------------------------------------
verdict() {
  [ "$(jq 'length' <<<"$FAILING")" -gt 0 ]  && { echo red; return; }
  [ "$(jq 'length' <<<"$BLOCKING")" -gt 0 ] && { echo blocked; return; }
  [ "$(jq 'length' <<<"$PENDING")" -gt 0 ]  && { echo yellow; return; }
  [ "$CR_LANDED" != "true" ]                && { echo yellow; return; }
  [ "$CHECK_COUNT" -eq 0 ]                  && { echo blocked; return; }
  [ "$ACTIONABLE" -gt 0 ]                   && { echo blocked; return; }
  echo green
}
VERDICT="$(verdict)"

REASON="$VERDICT"
case "$VERDICT" in
  yellow)  [ "$CR_LANDED" != "true" ] && REASON="review not yet landed for head ${HEAD_SHA:0:8} (state=$CR_STATE provider=$REVIEW_PROVIDER)" || REASON="checks pending: $(jq -r 'join(",")' <<<"$PENDING")" ;;
  red)     REASON="failing checks: $(jq -r 'join(",")' <<<"$FAILING")" ;;
  blocked) [ "$ACTIONABLE" -gt 0 ] && REASON="$ACTIONABLE unresolved actionable review thread(s)" || REASON="blocking/neutral or empty check set" ;;
  green)
    case "$CR_STATE" in
      disabled)     REASON="all checks pass; review gating disabled; 0 actionable threads" ;;
      unconfigured) REASON="all checks pass; no $REVIEW_PROVIDER review signal for head ${HEAD_SHA:0:8} (repo may not be onboarded); 0 actionable threads" ;;
      skipped)      REASON="all checks pass; review skipped head ${HEAD_SHA:0:8}; 0 actionable threads" ;;
      *)            REASON="all checks pass; review landed for head ${HEAD_SHA:0:8}; 0 actionable threads" ;;
    esac
    ;;
esac

CR_MARKER_BOOL=false; [ "$CR_MARKER" -eq 1 ] && CR_MARKER_BOOL=true
CR_SKIP_BOOL=false; [ "$CR_SKIP" -eq 1 ] && CR_SKIP_BOOL=true
jq -n \
  --arg verdict "$VERDICT" \
  --arg reason "$REASON" \
  --arg head "$HEAD_SHA" \
  --arg crHead "$CR_REVIEWED_HEAD" \
  --arg crStatus "$CR_STATUS" \
  --arg crState "$CR_STATE" \
  --arg reviewProvider "$REVIEW_PROVIDER" \
  --argjson crLanded "$CR_LANDED" \
  --argjson crMarker "$CR_MARKER_BOOL" \
  --argjson crSkipped "$CR_SKIP_BOOL" \
  --argjson minsSince "${MINS_SINCE:-0}" \
  --argjson unresolved "${UNRESOLVED:-0}" \
  --argjson actionable "${ACTIONABLE:-0}" \
  --argjson failing "$FAILING" \
  --argjson pending "$PENDING" \
  --argjson blocking "$BLOCKING" \
  --argjson checkCount "${CHECK_COUNT:-0}" \
  --arg pr "$PR" \
  '{
    verdict: $verdict,
    reason: $reason,
    pr: ($pr|tonumber),
    head: $head,
    reviewProvider: $reviewProvider,
    coderabbitReviewedHead: (if $crHead=="" then null else $crHead end),
    coderabbitReviewedCurrentHead: ($crHead==$head and $crHead!=""),
    coderabbitStatus: $crStatus,
    coderabbitState: $crState,
    coderabbitLanded: $crLanded,
    coderabbitSkipped: $crSkipped,
    coderabbitInProgressMarker: $crMarker,
    minutesSinceHeadPush: $minsSince,
    unresolvedThreads: $unresolved,
    unresolvedActionable: $actionable,
    failingChecks: $failing,
    pendingChecks: $pending,
    blockingNeutral: $blocking,
    checkCount: $checkCount
  }'

case "$VERDICT" in
  green)   exit 0 ;;
  yellow)  exit 10 ;;
  red)     exit 20 ;;
  blocked) exit 30 ;;
  *)       exit 1 ;;
esac
