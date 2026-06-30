#!/usr/bin/env bash
# Deterministic Shipwright CI readiness gate.
#
# Prints a single JSON verdict to stdout and never mutates anything. Canonical computation behind the
# `checks-gate` skill — `/sw-watch-ci` and stabilize invoke it instead of ad-hoc host CLI calls.
#
# Per-head review state comes from providers/review/<provider>.sh (executable adapter seam).
#
# Usage: check-gate.py [PR_NUMBER]
# Config: .cursor/workflow.config.json or workflow.config.json
# Env: SW_GATE_NOW — unix seconds override for deterministic tests (grace window)
set -uo pipefail

CHECKS="$(mktemp "${TMPDIR:-/tmp}/sw-gate-checks.XXXXXX")"
ISSUE_COMMENTS="$(mktemp "${TMPDIR:-/tmp}/sw-gate-comments.XXXXXX")"
trap 'rm -f "$CHECKS" "$ISSUE_COMMENTS"' EXIT

host_verb() {
  bash "$SCRIPT_DIR/host.sh" --root "$ROOT" "$@"
}

host_data() {
  local out
  out="$(host_verb "$@")" || true
  python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(json.dumps(d.get('data'))) if d.get('verdict')=='ok' else sys.exit(1)" "$out" 2>/dev/null
}


# --- repo + config ------------------------------------------------------------
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
# shellcheck source=sw-resolve-plugin-root.py
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/sw-resolve-plugin-root.py"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(sw_resolve_plugin_root "$SCRIPT_DIR")"
CONFIG=""
for p in "$ROOT/.cursor/workflow.config.json" "$ROOT/workflow.config.json"; do
  [ -f "$p" ] && CONFIG="$p" && break
done
cfg() {
  if [ -n "$CONFIG" ]; then jq -r "$1 // \"$2\"" "$CONFIG" 2>/dev/null || echo "$2"; else echo "$2"; fi
}
NEUTRAL_PASS="$(cfg '.checks.treatNeutralAsPass' 'true')"
GRACE_MIN="$(cfg '.coderabbit.reviewGraceMinutes' '15')"
REVIEW_PROVIDER="$(cfg '.review.provider' 'none')"
REVIEW_PROVIDER_SET=false
REVIEW_PROVIDER_RAW=""
if [ -n "$CONFIG" ] && jq -e '.review.provider' "$CONFIG" >/dev/null 2>&1; then
  REVIEW_PROVIDER_SET=true
  REVIEW_PROVIDER_RAW="$(jq -r '.review.provider' "$CONFIG")"
fi
case "$REVIEW_PROVIDER" in
  [a-z0-9-]*) ;;
  *)
    echo "{\"verdict\":\"blocked\",\"reason\":\"invalid review.provider: $REVIEW_PROVIDER\"}"
    exit 30
    ;;
esac
ALLOW_JSON='[]'
[ -n "$CONFIG" ] && ALLOW_JSON="$(jq -c '.checks.neutralAllowlist // []' "$CONFIG" 2>/dev/null || echo '[]')"

# --- PR test-plan manifest (PRD 016 — advisory vs required CI jobs) ------------
PR_TEST_PLAN_MANIFEST="$ROOT/core/sw-reference/pr-test-plan.manifest.json"
if [ -n "$CONFIG" ]; then
  MANIFEST_CFG="$(jq -r '.ci.prTestPlanManifest // .verify.prTestPlanManifest // empty' "$CONFIG" 2>/dev/null || true)"
  [ -n "$MANIFEST_CFG" ] && [ -f "$ROOT/$MANIFEST_CFG" ] && PR_TEST_PLAN_MANIFEST="$ROOT/$MANIFEST_CFG"
fi
PR_TEST_PLAN='null'
ADVISORY_JOBS='[]'
REQUIRED_JOBS='[]'
if [ -f "$PR_TEST_PLAN_MANIFEST" ]; then
  PR_TEST_PLAN="$(jq -c '.' "$PR_TEST_PLAN_MANIFEST" 2>/dev/null || echo 'null')"
  ADVISORY_JOBS="$(jq -c '[.fixtures[]?|select(.classification=="advisory")|.ciJobName]' "$PR_TEST_PLAN_MANIFEST" 2>/dev/null || echo '[]')"
  REQUIRED_JOBS="$(jq -c '[.fixtures[]?|select(.classification=="required")|.ciJobName]' "$PR_TEST_PLAN_MANIFEST" 2>/dev/null || echo '[]')"
fi

# --- host provider (local-evidence path for none) -----------------------------
HOST_PROVIDER="$(python3 "$SCRIPT_DIR/host_lib.py" --root "$ROOT" resolve 2>/dev/null | jq -r '.provider // ""' 2>/dev/null || echo "")"

GATE_DEPRECATIONS='[]'

local_evidence_gate() {
  HEAD_SHA="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || true)"
  BRANCH="$(git -C "$ROOT" branch --show-current 2>/dev/null || true)"
  if [ -z "$HEAD_SHA" ]; then
    echo '{"verdict":"blocked","reason":"not a git repository","source":"local-evidence"}'
    exit 30
  fi
  REPO_META="$(host_verb repo-meta 2>/dev/null || true)"
  OWNER_REPO="$(python3 -c "import json,sys; d=json.loads(sys.argv[1] or '{}'); print((d.get('data') or {}).get('nameWithOwner','local/repo'))" "$REPO_META" 2>/dev/null || echo 'local/repo')"
  OWNER="${OWNER_REPO%/*}"
  REPO="${OWNER_REPO#*/}"
  CHECKS_OUT="$(host_verb checks --sha "$HEAD_SHA" 2>/dev/null || true)"
  python3 -c "import json,sys; d=json.loads(sys.argv[1] or '{}'); open(sys.argv[2],'w').write(json.dumps(d.get('data') or []))" "$CHECKS_OUT" "$CHECKS" 2>/dev/null || echo '[]' > "$CHECKS"
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
  SPLIT="$(jq -c --argjson adv "$ADVISORY_JOBS" --argjson fail "$FAILING" '
    ($fail|map(select(. as $n | ($adv|index($n)|not)))) as $req |
    ($fail|map(select(. as $n | ($adv|index($n))))) as $advFail |
    {requiredFailing: $req, advisoryFailing: $advFail}
  ' <<<"{}")"
  REQUIRED_FAILING="$(jq -c '.requiredFailing' <<<"$SPLIT")"
  ADVISORY_FAILING="$(jq -c '.advisoryFailing' <<<"$SPLIT")"
  UNRESOLVED=0
  ACTIONABLE=0
  HAS_PER_HEAD=true
  CR_STATE="off"; CR_LANDED=true
  CR_REVIEWED_HEAD=""; CR_STATUS="off"
  CR_MARKER=0; CR_SKIP=0; MINS_SINCE=0
  verdict() {
    [ "$(jq 'length' <<<"$REQUIRED_FAILING")" -gt 0 ] && { echo red; return; }
    [ "$(jq 'length' <<<"$BLOCKING")" -gt 0 ] && { echo blocked; return; }
    [ "$(jq 'length' <<<"$PENDING")" -gt 0 ]  && { echo yellow; return; }
    [ "$CHECK_COUNT" -eq 0 ]                  && { echo blocked; return; }
    echo green
  }
  VERDICT="$(verdict)"
  REASON="$VERDICT"
  case "$VERDICT" in
    yellow)  REASON="checks pending: $(jq -r 'join(",")' <<<"$PENDING")" ;;
    red)     REASON="failing checks: $(jq -r 'join(",")' <<<"$REQUIRED_FAILING")" ;;
    blocked) REASON="blocking/neutral or empty check set" ;;
    green)   REASON="local-evidence: all local checks pass; review gating off; 0 actionable threads" ;;
  esac
  
CR_MARKER_BOOL=false; CR_SKIP_BOOL=false
  jq -n     --arg verdict "$VERDICT"     --arg reason "$REASON"     --arg head "$HEAD_SHA"     --arg branch "$BRANCH"     --arg crHead "$CR_REVIEWED_HEAD"     --arg crStatus "$CR_STATUS"     --arg crState "$CR_STATE"     --arg reviewProvider "$REVIEW_PROVIDER"     --argjson crLanded "$CR_LANDED"     --argjson crMarker "$CR_MARKER_BOOL"     --argjson crSkipped "$CR_SKIP_BOOL"     --argjson minsSince 0     --argjson unresolved 0     --argjson actionable 0     --argjson failing "$FAILING"     --argjson requiredFailing "$REQUIRED_FAILING"     --argjson advisoryFailing "$ADVISORY_FAILING"     --argjson prTestPlanRequired "$REQUIRED_JOBS"     --argjson prTestPlanAdvisory "$ADVISORY_JOBS"     --argjson prTestPlanManifest "$PR_TEST_PLAN"     --argjson pending "$PENDING"     --argjson blocking "$BLOCKING"     --argjson checkCount "${CHECK_COUNT:-0}"     --argjson deprecations "$GATE_DEPRECATIONS"     '{
      verdict: $verdict,
      reason: $reason,
      source: "local-evidence",
      pr: null,
      head: $head,
      branch: $branch,
      reviewProvider: $reviewProvider,
      deprecations: $deprecations,
      coderabbitReviewedHead: null,
      coderabbitReviewedCurrentHead: false,
      coderabbitStatus: $crStatus,
      coderabbitState: $crState,
      coderabbitLanded: $crLanded,
      coderabbitSkipped: $crSkipped,
      coderabbitInProgressMarker: $crMarker,
      minutesSinceHeadPush: $minsSince,
      unresolvedThreads: $unresolved,
      unresolvedActionable: $actionable,
      failingChecks: $failing,
      requiredFailingChecks: $requiredFailing,
      advisoryFailingChecks: $advisoryFailing,
      prTestPlan: (if $prTestPlanManifest==null then null else {
        manifest: $prTestPlanManifest,
        requiredJobs: $prTestPlanRequired,
        advisoryJobs: $prTestPlanAdvisory
      } end),
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
}

if [ "$HOST_PROVIDER" = "none" ]; then
  local_evidence_gate
fi

# --- resolve PR + head (host verbs) -------------------------------------------
PR="${1:-}"
if [ -z "$PR" ]; then
  RESOLVE_OUT="$(host_verb resolve-pr-for-branch 2>/dev/null || true)"
  PR="$(python3 -c "import json,sys; d=json.loads(sys.argv[1] or '{}'); items=d.get('data') or []; print(items[0].get('number','') if items else '')" "$RESOLVE_OUT" 2>/dev/null || true)"
fi
if [ -z "$PR" ]; then
  echo '{"verdict":"blocked","reason":"no open PR for current branch"}'
  exit 30
fi
PR_VIEW="$(host_verb pr-view --number "$PR" 2>/dev/null || true)"
HEAD_SHA="$(python3 -c "import json,sys; d=json.loads(sys.argv[1] or '{}'); print((d.get('data') or {}).get('headRefOid',''))" "$PR_VIEW" 2>/dev/null || true)"
MERGEABLE="$(python3 -c "import json,sys; d=json.loads(sys.argv[1] or '{}'); print((d.get('data') or {}).get('mergeable',''))" "$PR_VIEW" 2>/dev/null || true)"
MERGE_STATE="$(python3 -c "import json,sys; d=json.loads(sys.argv[1] or '{}'); print((d.get('data') or {}).get('mergeStateStatus',''))" "$PR_VIEW" 2>/dev/null || true)"
REPO_META="$(host_verb repo-meta 2>/dev/null || true)"
OWNER_REPO="$(python3 -c "import json,sys; d=json.loads(sys.argv[1] or '{}'); print((d.get('data') or {}).get('nameWithOwner',''))" "$REPO_META" 2>/dev/null || true)"
if [ -z "$HEAD_SHA" ] || [ -z "$OWNER_REPO" ]; then
  echo '{"verdict":"blocked","reason":"incomplete host metadata (head or repo)"}'
  exit 30
fi
if [ "$MERGEABLE" = "CONFLICTING" ] || [ "$MERGE_STATE" = "DIRTY" ]; then
  echo "{\"verdict\":\"blocked\",\"reason\":\"merge-conflict\",\"mergeable\":\"$MERGEABLE\",\"mergeStateStatus\":\"$MERGE_STATE\",\"recommendedCommand\":\"/sw-stabilize\"}"
  exit 30
fi
OWNER="${OWNER_REPO%/*}"
REPO="${OWNER_REPO#*/}"

# --- checks -------------------------------------------------------------------
CHECKS_OUT="$(host_verb checks --number "$PR" --sha "$HEAD_SHA" 2>/dev/null || true)"
python3 -c "import json,sys; d=json.loads(sys.argv[1] or '{}'); open(sys.argv[2],'w').write(json.dumps(d.get('data') or []))" "$CHECKS_OUT" "$CHECKS" 2>/dev/null || echo '[]' > "$CHECKS"
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

# Split manifest-classified PR test-plan job failures (advisory ≠ merge-blocking).
SPLIT="$(jq -c --argjson adv "$ADVISORY_JOBS" --argjson fail "$FAILING" '
  ($fail|map(select(. as $n | ($adv|index($n)|not)))) as $req |
  ($fail|map(select(. as $n | ($adv|index($n))))) as $advFail |
  {requiredFailing: $req, advisoryFailing: $advFail}
' <<<"{}")"
REQUIRED_FAILING="$(jq -c '.requiredFailing' <<<"$SPLIT")"
ADVISORY_FAILING="$(jq -c '.advisoryFailing' <<<"$SPLIT")"

# --- unresolved review threads (host verb) ------------------------------------
UNRESOLVED=0
ACTIONABLE=0
THREADS_OUT="$(host_verb review-threads --number "$PR" 2>/dev/null || true)"
UNRESOLVED="$(python3 -c "import json,sys; d=json.loads(sys.argv[1] or '{}'); print((d.get('data') or {}).get('unresolved',0))" "$THREADS_OUT" 2>/dev/null || echo 0)"
ACTIONABLE="$(python3 -c "import json,sys; d=json.loads(sys.argv[1] or '{}'); print((d.get('data') or {}).get('actionable',0))" "$THREADS_OUT" 2>/dev/null || echo 0)"

# --- review per-head state (executable adapter seam) --------------------------
# Opt-out: review.provider="none" (explicit) or review.enabled=false (deprecated).
# Never-configured (provider key absent) → unconfigured; explicit opt-out → off.
REVIEW_ENABLED="true"
if [ -n "$CONFIG" ]; then
  REVIEW_ENABLED="$(jq -r 'if .review and (.review|has("enabled")) then (.review.enabled|tostring) else "true" end' "$CONFIG" 2>/dev/null || echo true)"
fi
GATE_DEPRECATIONS='[]'
if [ "$REVIEW_ENABLED" = "false" ]; then
  GATE_DEPRECATIONS='["review.enabled is deprecated; use review.provider:\"none\""]'
  echo "warning: review.enabled is deprecated; use review.provider:\"none\"" >&2
fi

if [ "$REVIEW_ENABLED" = "false" ] || { [ "$REVIEW_PROVIDER_SET" = true ] && [ "$REVIEW_PROVIDER_RAW" = "none" ]; }; then
  HAS_PER_HEAD=true
  CR_STATE="off"; CR_LANDED=true
  CR_REVIEWED_HEAD=""; CR_STATUS="off"
  CR_MARKER=0; CR_SKIP=0; MINS_SINCE=0
elif [ "$REVIEW_PROVIDER_SET" = false ]; then
  HAS_PER_HEAD=true
  CR_STATE="unconfigured"; CR_LANDED=true
  CR_REVIEWED_HEAD=""; CR_STATUS="unconfigured"
  CR_MARKER=0; CR_SKIP=0; MINS_SINCE=0
elif [ "$REVIEW_PROVIDER" = "none" ]; then
  HAS_PER_HEAD=true
  CR_STATE="off"; CR_LANDED=true
  CR_REVIEWED_HEAD=""; CR_STATUS="off"
  CR_MARKER=0; CR_SKIP=0; MINS_SINCE=0
else
  ADAPTER="$PLUGIN_ROOT/providers/review/${REVIEW_PROVIDER}.sh"
  if [ ! -f "$ADAPTER" ]; then
    echo "{\"verdict\":\"blocked\",\"reason\":\"unknown review provider: $REVIEW_PROVIDER\"}"
    exit 30
  fi
  export SW_PR="$PR" SW_HEAD_SHA="$HEAD_SHA" SW_OWNER="$OWNER" SW_REPO="$REPO"
  export SW_OWNER_REPO="$OWNER_REPO" SW_CHECKS_FILE="$CHECKS" SW_ISSUE_COMMENTS_FILE="$ISSUE_COMMENTS"
  export SW_GRACE_MIN="$GRACE_MIN"
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
  [ "$(jq 'length' <<<"$REQUIRED_FAILING")" -gt 0 ] && { echo red; return; }
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
  red)     REASON="failing checks: $(jq -r 'join(",")' <<<"$REQUIRED_FAILING")" ;;
  blocked) [ "$ACTIONABLE" -gt 0 ] && REASON="$ACTIONABLE unresolved actionable review thread(s)" || REASON="blocking/neutral or empty check set" ;;
  green)
    if [ "$(jq 'length' <<<"$ADVISORY_FAILING")" -gt 0 ]; then
      REASON="required checks pass; advisory failing (non-blocking): $(jq -r 'join(",")' <<<"$ADVISORY_FAILING")"
    else
    case "$CR_STATE" in
      off)            REASON="all checks pass; review gating off; 0 actionable threads" ;;
      unconfigured) REASON="all checks pass; review off by default — never configured; 0 actionable threads" ;;
      skipped)      REASON="all checks pass; review skipped head ${HEAD_SHA:0:8}; 0 actionable threads" ;;
      *)            REASON="all checks pass; review landed for head ${HEAD_SHA:0:8}; 0 actionable threads" ;;
    esac
    fi
    ;;
esac

# PRD 038 R15 — advisory only when PR touches scripts/ (no hard block).
if [ "$VERDICT" = "green" ] && [ -n "${PR:-}" ] && [ -n "${HEAD_SHA:-}" ]; then
  BASE_REF="$(python3 -c "import json,sys; d=json.loads(sys.argv[1] or '{}'); print((d.get('data') or {}).get('baseRefName',''))" "$PR_VIEW" 2>/dev/null || true)"
  if [ -n "$BASE_REF" ]; then
    git -C "$ROOT" fetch -q origin "$BASE_REF" 2>/dev/null || true
    MERGE_BASE="$(git -C "$ROOT" merge-base "origin/${BASE_REF}" "$HEAD_SHA" 2>/dev/null || true)"
    if [ -n "$MERGE_BASE" ] && git -C "$ROOT" diff --name-only "$MERGE_BASE" "$HEAD_SHA" 2>/dev/null | grep -q '^scripts/'; then
      REASON="${REASON}; advisory: PR touches scripts/ — consider python3 scripts/build-chain-sync.py"
    fi
  fi
fi

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
  --argjson requiredFailing "$REQUIRED_FAILING" \
  --argjson advisoryFailing "$ADVISORY_FAILING" \
  --argjson prTestPlanRequired "$REQUIRED_JOBS" \
  --argjson prTestPlanAdvisory "$ADVISORY_JOBS" \
  --argjson prTestPlanManifest "$PR_TEST_PLAN" \
  --argjson pending "$PENDING" \
  --argjson blocking "$BLOCKING" \
  --argjson checkCount "${CHECK_COUNT:-0}" \
  --arg pr "$PR" \
  --argjson deprecations "$GATE_DEPRECATIONS" \
  '{
    verdict: $verdict,
    reason: $reason,
    pr: ($pr|tonumber),
    head: $head,
    reviewProvider: $reviewProvider,
    deprecations: $deprecations,
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
    requiredFailingChecks: $requiredFailing,
    advisoryFailingChecks: $advisoryFailing,
    prTestPlan: (if $prTestPlanManifest==null then null else {
      manifest: $prTestPlanManifest,
      requiredJobs: $prTestPlanRequired,
      advisoryJobs: $prTestPlanAdvisory
    } end),
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
