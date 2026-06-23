#!/usr/bin/env bash
# CodeRabbit executable review adapter for the gate path.
# Reads context from env (set by check-gate.sh); prints normalized JSON to stdout.
set -euo pipefail

: "${PF_PR:?}"
: "${PF_HEAD_SHA:?}"
: "${PF_OWNER_REPO:?}"
: "${PF_CHECKS_FILE:?}"
: "${PF_ISSUE_COMMENTS_FILE:?}"
: "${PF_GRACE_MIN:=15}"

OWNER="${PF_OWNER:-${PF_OWNER_REPO%/*}}"
REPO="${PF_REPO:-${PF_OWNER_REPO#*/}}"
PR="$PF_PR"
HEAD_SHA="$PF_HEAD_SHA"
CHECKS="$PF_CHECKS_FILE"
ISSUE_COMMENTS="$PF_ISSUE_COMMENTS_FILE"
GRACE_MIN="$PF_GRACE_MIN"

CR_STATUS="$(jq -r 'first(.[]|select(.name|test("coderabbit";"i"))|.state) // "absent"' "$CHECKS" 2>/dev/null || echo absent)"

CR_REVIEWED_HEAD=""
if [ -n "$OWNER" ] && [ -n "$REPO" ]; then
  REVIEWS="$(gh api graphql -f query='query($o:String!,$r:String!,$p:Int!){repository(owner:$o,name:$r){pullRequest(number:$p){reviews(last:50){nodes{author{login} submittedAt commit{oid}}}}}}' \
    -F o="$OWNER" -F r="$REPO" -F p="$PR" 2>/dev/null || echo '{}')"
  CR_REVIEWED_HEAD="$(jq -r '[.data.repository.pullRequest.reviews.nodes[]?|select(.author.login|test("coderabbit";"i"))]|(sort_by(.submittedAt)|last|.commit.oid // "")' <<<"$REVIEWS" 2>/dev/null || echo "")"
fi

gh api "repos/$PF_OWNER_REPO/issues/$PR/comments" --paginate > "$ISSUE_COMMENTS" 2>/dev/null || true
[ -s "$ISSUE_COMMENTS" ] || echo '[]' > "$ISSUE_COMMENTS"
CR_MARKER=0
CR_SKIP=0
CR_DONE=0
CR_BODY="$(jq -r '[.[]|select((.user.login|test("coderabbit";"i")) and (.body|test("summarize by coderabbit";"i")))]|last|.body // ""' "$ISSUE_COMMENTS" 2>/dev/null || echo "")"
[ -z "$CR_BODY" ] && CR_BODY="$(jq -r '[.[]|select(.user.login|test("coderabbit";"i"))]|last|.body // ""' "$ISSUE_COMMENTS" 2>/dev/null || echo "")"
if printf '%s' "$CR_BODY" | grep -qiE 'Currently processing new changes|review in progress by coderabbit'; then
  CR_MARKER=1
fi
if printf '%s' "$CR_BODY" | grep -qiE 'skip review by coderabbit|No new commits to review since the last review'; then
  CR_SKIP=1
fi
if printf '%s' "$CR_BODY" | grep -qiE 'No actionable comments were generated|Actionable comments posted:'; then
  CR_DONE=1
fi

CR_INSTALLED=false
[ -n "$CR_REVIEWED_HEAD" ] && CR_INSTALLED=true
[ "$CR_STATUS" != "absent" ] && CR_INSTALLED=true
[ "$CR_MARKER" -eq 1 ] && CR_INSTALLED=true
[ "$CR_SKIP" -eq 1 ] && CR_INSTALLED=true
[ "$CR_DONE" -eq 1 ] && CR_INSTALLED=true

HEAD_TIME="$(gh api "repos/$PF_OWNER_REPO/commits/$HEAD_SHA" --jq '.commit.committer.date' 2>/dev/null | { read -r d; [ -n "$d" ] && { date -u -j -f "%Y-%m-%dT%H:%M:%SZ" "$d" +%s 2>/dev/null || date -u -d "$d" +%s 2>/dev/null; } || echo 0; })"
NOW="${PF_GATE_NOW:-$(date +%s)}"
MINS_SINCE=0
[ "${HEAD_TIME:-0}" -gt 0 ] && MINS_SINCE=$(( (NOW - HEAD_TIME) / 60 ))

CR_LANDED=false
CR_STATE="in-flight"
if [ "$CR_INSTALLED" != "true" ]; then
  if [ "$MINS_SINCE" -lt "$GRACE_MIN" ]; then
    CR_STATE="in-flight"; CR_LANDED=false
  else
    CR_STATE="absent"; CR_LANDED=true
  fi
elif [ "$CR_MARKER" -eq 1 ] || [ "$CR_STATUS" = "PENDING" ] || [ "$CR_STATUS" = "IN_PROGRESS" ]; then
  CR_STATE="in-flight"; CR_LANDED=false
elif [ "$CR_STATUS" = "SUCCESS" ] || [ "$CR_REVIEWED_HEAD" = "$HEAD_SHA" ]; then
  if [ "$CR_SKIP" -eq 1 ]; then CR_STATE="skipped"; else CR_STATE="landed"; fi
  CR_LANDED=true
elif { [ "$CR_SKIP" -eq 1 ] || [ "$CR_DONE" -eq 1 ]; } && [ "$MINS_SINCE" -ge "$GRACE_MIN" ]; then
  if [ "$CR_SKIP" -eq 1 ]; then CR_STATE="skipped"; else CR_STATE="landed"; fi
  CR_LANDED=true
else
  CR_STATE="in-flight"; CR_LANDED=false
fi

CR_MARKER_BOOL=false; [ "$CR_MARKER" -eq 1 ] && CR_MARKER_BOOL=true
CR_SKIP_BOOL=false; [ "$CR_SKIP" -eq 1 ] && CR_SKIP_BOOL=true

jq -n \
  --arg state "$CR_STATE" \
  --argjson landed "$CR_LANDED" \
  --arg reviewedHead "$CR_REVIEWED_HEAD" \
  --arg statusContext "$CR_STATUS" \
  --argjson inProgressMarker "$CR_MARKER_BOOL" \
  --argjson skipped "$CR_SKIP_BOOL" \
  --argjson minsSince "$MINS_SINCE" \
  '{
    capabilities: { perHeadState: true },
    perHeadState: $state,
    perHeadLanded: $landed,
    reviewedHead: (if $reviewedHead=="" then null else $reviewedHead end),
    statusContext: $statusContext,
    inProgressMarker: $inProgressMarker,
    skipped: $skipped,
    minutesSinceHeadPush: $minsSince
  }'
