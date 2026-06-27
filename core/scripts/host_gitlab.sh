#!/usr/bin/env bash
# GitLab host adapter — REST merge requests (PRD 026 Phase 4).
#
# Usage: host_gitlab.sh --root PATH <verb> [--key value ...]
set -euo pipefail

ROOT=""
VERB=""
ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root) ROOT="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,4p' "$0"
      exit 0
      ;;
    *)
      VERB="$1"
      shift
      ARGS=("$@")
      break
      ;;
  esac
done

[[ -n "$ROOT" ]] || ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TRANSPORT="$SCRIPT_DIR/host_transport.sh"
FIXTURE_DIR="$ROOT/scripts/test/fixtures/host"
FIXTURE="${SW_HOST_FIXTURE:-}"
PROVIDER="gitlab"

kv() {
  local key="$1" default="${2:-}"
  local i=0
  while [[ $i -lt ${#ARGS[@]} ]]; do
    if [[ "${ARGS[$i]}" == "--$key" && $((i + 1)) -lt ${#ARGS[@]} ]]; then
      echo "${ARGS[$((i + 1))]}"
      return 0
    fi
    i=$((i + 1))
  done
  echo "$default"
}

context_json() {
  python3 - "$ROOT" <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "scripts"))
from host_lib import gitlab_api_base, host_section, load_workflow_config, parse_owner_repo, resolve_provider, resolve_token_env, url_encode_project

root = Path(sys.argv[1])
resolved = resolve_provider(root)
cfg = load_workflow_config(root)
host = host_section(cfg)
remote_url = resolved.get("remoteUrl")
slug = parse_owner_repo(remote_url)
owner, repo = slug if slug else ("", "")
project = url_encode_project(owner, repo) if owner and repo else ""
print(json.dumps({
    "provider": "gitlab",
    "tokenEnv": resolve_token_env(host, "gitlab"),
    "apiBase": gitlab_api_base(host),
    "owner": owner,
    "repo": repo,
    "project": project,
    "nameWithOwner": f"{owner}/{repo}" if owner and repo else "",
    "degraded": resolved.get("degraded", False),
    "degradedReason": resolved.get("degradedReason"),
}))
PY
}

CTX="$(context_json)"
OWNER="$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['owner'])" "$CTX")"
REPO="$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['repo'])" "$CTX")"
PROJECT="$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['project'])" "$CTX")"
API_BASE="$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('apiBase','https://gitlab.com/api/v4'))" "$CTX")"
TOKEN_ENV="$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('tokenEnv','GITLAB_TOKEN'))" "$CTX")"

emit() {
  python3 -c 'import json,sys; print(json.dumps(json.loads(sys.argv[1]), indent=2))' "$1"
}

fail_json() {
  local reason="$1" msg="${2:-}"
  emit "{\"verdict\":\"fail\",\"verb\":\"$VERB\",\"provider\":\"$PROVIDER\",\"reason\":\"$reason\",\"message\":\"$msg\"}"
  exit 30
}

degraded_json() {
  local reason="$1"
  emit "{\"verdict\":\"degraded\",\"verb\":\"$VERB\",\"provider\":\"$PROVIDER\",\"reason\":\"$reason\",\"retryable\":false}"
  exit 0
}

if [[ -z "$FIXTURE" && "$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('degraded',False))" "$CTX")" == "True" ]]; then
  degraded_json "$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('degradedReason','missing-token'))" "$CTX")"
fi

mock_fixture() {
  local name="$1"
  [[ -n "$FIXTURE" ]] || return 1
  local f="$FIXTURE_DIR/${name}.json"
  if [[ -f "$f" ]]; then
    cat "$f"
    return 0
  fi
  case "$name" in
    repo-meta-*) f="$FIXTURE_DIR/repo-meta-${FIXTURE}.json" ;;
    pr-view-*) f="$FIXTURE_DIR/pr-view-${FIXTURE}.json" ;;
    pr-list-*) f="$FIXTURE_DIR/pr-list-${FIXTURE}.json" ;;
    pr-create-*) f="$FIXTURE_DIR/pr-create-${FIXTURE}.json" ;;
    pr-close-*) f="$FIXTURE_DIR/pr-close-${FIXTURE}.json" ;;
    checks-*) f="$FIXTURE_DIR/checks-green.json" ;;
    review-threads-*) f="$FIXTURE_DIR/review-threads-blocked-threads.json" ;;
    *) f="" ;;
  esac
  if [[ -n "$f" && -f "$f" ]]; then
    cat "$f"
    return 0
  fi
  return 1
}

http_get() {
  local url="$1"
  if [[ -n "$FIXTURE" ]]; then
    python3 - "$FIXTURE_DIR" "$FIXTURE" "$url" <<'PY'
import json, sys
from pathlib import Path
fixture_dir, fixture, url = sys.argv[1], sys.argv[2], sys.argv[3]
map_file = Path(fixture_dir) / f"transport-{fixture}.json"
if not map_file.is_file():
    sys.exit(1)
mapping = json.loads(map_file.read_text())
for pattern, body in mapping.items():
    if pattern in url or url.endswith(pattern):
        print(json.dumps({"verdict":"ok","status":200,"body":body}))
        sys.exit(0)
sys.exit(1)
PY
    return $?
  fi
  "$TRANSPORT" --root "$ROOT" --provider "$PROVIDER" --method GET --url "$url" --token-env "$TOKEN_ENV"
}

http_post() {
  local url="$1" body_file="$2"
  "$TRANSPORT" --root "$ROOT" --provider "$PROVIDER" --method POST --url "$url" --token-env "$TOKEN_ENV" --body-file "$body_file"
}

http_put() {
  local url="$1" body_file="$2"
  "$TRANSPORT" --root "$ROOT" --provider "$PROVIDER" --method PUT --url "$url" --token-env "$TOKEN_ENV" --body-file "$body_file"
}

parse_transport_body() {
  python3 -c 'import json,sys; d=json.load(sys.stdin); b=d.get("body") or ""; print(b if isinstance(b,str) else json.dumps(b))' <<<"$1"
}

gl_state_filter() {
  case "$1" in
    open|opened) echo "opened" ;;
    closed) echo "closed" ;;
    merged) echo "merged" ;;
    all) echo "all" ;;
    *) echo "opened" ;;
  esac
}

gl_mr_to_view() {
  python3 - "$1" <<'PY'
import json, sys
mr = json.loads(sys.argv[1])
state = (mr.get("state") or "").lower()
if mr.get("merged_at"):
    state = "merged"
merge_status = (mr.get("merge_status") or "unknown").lower()
mergeable = "MERGEABLE" if merge_status == "can_be_merged" else ("CONFLICTING" if merge_status == "cannot_be_merged" else "UNKNOWN")
print(json.dumps({
    "number": mr.get("iid") or mr.get("id"),
    "url": mr.get("web_url"),
    "headRefName": mr.get("source_branch"),
    "headRefOid": mr.get("sha") or ((mr.get("diff_refs") or {}).get("head_sha")),
    "baseRefName": mr.get("target_branch"),
    "state": state.upper(),
    "isDraft": bool(mr.get("draft") or mr.get("work_in_progress")),
    "mergeable": mergeable,
    "mergeStateStatus": merge_status.upper(),
    "title": mr.get("title"),
    "body": mr.get("description"),
    "mergedAt": mr.get("merged_at"),
    "mergeCommit": {"oid": mr.get("merge_commit_sha")} if mr.get("merge_commit_sha") else None,
}))
PY
}

case "$VERB" in
  repo-meta)
    if mock_fixture "repo-meta-$FIXTURE"; then exit 0; fi
    [[ -n "$PROJECT" ]] || fail_json "missing-repo"
    resp="$(http_get "$API_BASE/projects/$PROJECT")" || fail_json "transport-failed"
    body="$(parse_transport_body "$resp")"
    emit "$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); ns=d.get('namespace') or {}; print(json.dumps({'verdict':'ok','verb':'repo-meta','provider':'gitlab','data':{'nameWithOwner':d.get('path_with_namespace'),'defaultBranch':d.get('default_branch'),'owner':ns.get('path') or ns.get('name'),'name':d.get('name')}}))" "$body")"
    ;;

  resolve-pr-for-branch)
    branch="$(kv branch "$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || true)")"
    [[ -n "$branch" ]] || fail_json "no-branch"
    ARGS=(--head "$branch" --state open "${ARGS[@]}")
    exec "$0" --root "$ROOT" pr-list "${ARGS[@]}"
    ;;

  pr-list)
    head="$(kv head "")"
    base="$(kv base "")"
    state="$(gl_state_filter "$(kv state open)")"
    limit="$(kv limit 30)"
    if mock_fixture "pr-list-$FIXTURE"; then exit 0; fi
    [[ -n "$PROJECT" ]] || fail_json "missing-repo"
    url="$API_BASE/projects/$PROJECT/merge_requests?state=$state&per_page=$limit"
    [[ -n "$head" ]] && url="${url}&source_branch=${head}"
    [[ -n "$base" ]] && url="${url}&target_branch=${base}"
    resp="$(http_get "$url")" || fail_json "transport-failed"
    body="$(parse_transport_body "$resp")"
    emit "$(python3 - "$body" <<'PY'
import json, sys
items = json.loads(sys.argv[1])
if not isinstance(items, list):
    items = []
out = []
for mr in items:
    state = (mr.get("state") or "").upper()
    if mr.get("merged_at"):
        state = "MERGED"
    out.append({
        "number": mr.get("iid") or mr.get("id"),
        "url": mr.get("web_url"),
        "headRefName": mr.get("source_branch"),
        "headRefOid": mr.get("sha"),
        "baseRefName": mr.get("target_branch"),
        "state": state,
        "title": mr.get("title"),
        "body": mr.get("description"),
    })
print(json.dumps({"verdict":"ok","verb":"pr-list","provider":"gitlab","data":out}))
PY
)"
    ;;

  pr-view)
    number="$(kv number "")"
    url_arg="$(kv url "")"
    if mock_fixture "pr-view-$FIXTURE"; then exit 0; fi
    [[ -n "$PROJECT" ]] || fail_json "missing-repo"
    if [[ -z "$number" && -n "$url_arg" ]]; then
      number="$(python3 -c "import re,sys; m=re.search(r'/merge_requests/(\\d+)', sys.argv[1]); print(m.group(1) if m else '')" "$url_arg")"
    fi
    [[ -n "$number" ]] || fail_json "missing-pr-number"
    resp="$(http_get "$API_BASE/projects/$PROJECT/merge_requests/$number")" || fail_json "transport-failed"
    body="$(parse_transport_body "$resp")"
    view="$(gl_mr_to_view "$body")"
    emit "$(python3 -c "import json,sys; print(json.dumps({'verdict':'ok','verb':'pr-view','provider':'gitlab','data':json.loads(sys.argv[1])}))" "$view")"
    ;;

  pr-head)
    number="$(kv number "")"
    if [[ -z "$number" ]]; then
      resolve="$(bash "$SCRIPT_DIR/host.sh" --root "$ROOT" resolve-pr-for-branch 2>/dev/null || true)"
      number="$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); items=d.get('data') or []; print(items[0]['number'] if items else '')" "$resolve" 2>/dev/null || true)"
    fi
    [[ -n "$number" ]] || fail_json "missing-pr-number"
    view_out="$(bash "$0" --root "$ROOT" pr-view --number "$number")"
    emit "$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(json.dumps({'verdict':'ok','verb':'pr-head','provider':'gitlab','data':{'headRefOid':d['data'].get('headRefOid'),'number':d['data'].get('number')}}))" "$view_out")"
    ;;

  pr-create)
    title="$(kv title "")"
    body="$(kv body "")"
    head="$(kv head "")"
    base="$(kv base "")"
    [[ -n "$title" && -n "$head" && -n "$base" ]] || fail_json "missing-fields"
    if mock_fixture "pr-create-$FIXTURE"; then exit 0; fi
    [[ -n "$PROJECT" ]] || fail_json "missing-repo"
    tmp="$(mktemp)"
    python3 - "$title" "$body" "$head" "$base" > "$tmp" <<'PY'
import json, sys
title, body, head, base = sys.argv[1:5]
print(json.dumps({"title": title, "description": body, "source_branch": head, "target_branch": base}))
PY
    resp="$(http_post "$API_BASE/projects/$PROJECT/merge_requests" "$tmp")" || fail_json "transport-failed"
    rm -f "$tmp"
    pr_body="$(parse_transport_body "$resp")"
    view="$(gl_mr_to_view "$pr_body")"
    emit "$(python3 -c "import json,sys; print(json.dumps({'verdict':'ok','verb':'pr-create','provider':'gitlab','data':json.loads(sys.argv[1])}))" "$view")"
    ;;

  pr-close)
    number="$(kv number "")"
    [[ -n "$number" ]] || fail_json "missing-pr-number"
    if mock_fixture "pr-close-$FIXTURE"; then exit 0; fi
    [[ -n "$PROJECT" ]] || fail_json "missing-repo"
    tmp="$(mktemp)"
    echo '{"state_event":"close"}' > "$tmp"
    resp="$(http_put "$API_BASE/projects/$PROJECT/merge_requests/$number" "$tmp")" || fail_json "transport-failed"
    rm -f "$tmp"
    body="$(parse_transport_body "$resp")"
    view="$(gl_mr_to_view "$body")"
    emit "$(python3 -c "import json,sys; print(json.dumps({'verdict':'ok','verb':'pr-close','provider':'gitlab','data':json.loads(sys.argv[1])}))" "$view")"
    ;;

  checks)
    sha="$(kv sha "")"
    number="$(kv number "")"
    if [[ -z "$sha" && -n "$number" ]]; then
      view_out="$(bash "$0" --root "$ROOT" pr-view --number "$number")"
      sha="$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['data'].get('headRefOid',''))" "$view_out")"
    fi
    [[ -n "$sha" ]] || fail_json "missing-sha"
    if mock_fixture "checks-$FIXTURE"; then exit 0; fi
    [[ -n "$PROJECT" ]] || fail_json "missing-repo"
    resp="$(http_get "$API_BASE/projects/$PROJECT/repository/commits/$sha/statuses?per_page=100")" || \
      resp="$(http_get "$API_BASE/projects/$PROJECT/pipelines?sha=$sha&per_page=100")" || fail_json "transport-failed"
    body="$(parse_transport_body "$resp")"
    checks="$(python3 - "$body" <<'PY'
import json, sys
data = json.loads(sys.argv[1])
items = data if isinstance(data, list) else (data.get("values") or data.get("pipelines") or [])
out = []
for r in items:
    status = (r.get("status") or r.get("state") or "").lower()
    if status in ("running", "pending", "in_progress", "created"):
        state = "IN_PROGRESS"
    elif status in ("success", "successful"):
        state = "SUCCESS"
    elif status in ("failed", "failure", "canceled", "cancelled"):
        state = "FAILURE"
    else:
        state = status.upper() or "PENDING"
    out.append({
        "name": r.get("name") or r.get("ref") or "check",
        "state": state,
        "bucket": "pass" if state in ("SUCCESS", "SKIPPED", "NEUTRAL") else ("fail" if state == "FAILURE" else "pending"),
        "link": r.get("target_url") or r.get("web_url") or "",
        "workflow": "",
    })
print(json.dumps(out))
PY
)"
    emit "$(python3 -c "import json,sys; print(json.dumps({'verdict':'ok','verb':'checks','provider':'gitlab','data':json.loads(sys.argv[1])}))" "$checks")"
    ;;

  review-threads)
    number="$(kv number "")"
    [[ -n "$number" ]] || fail_json "missing-pr-number"
    if mock_fixture "review-threads-$FIXTURE"; then exit 0; fi
    [[ -n "$PROJECT" ]] || fail_json "missing-repo"
    resp="$(http_get "$API_BASE/projects/$PROJECT/merge_requests/$number/discussions?per_page=100")" || fail_json "transport-failed"
    body="$(parse_transport_body "$resp")"
    emit "$(python3 - "$body" <<'PY'
import json, sys
discussions = json.loads(sys.argv[1])
if not isinstance(discussions, list):
    discussions = []
unresolved = actionable = 0
for d in discussions:
    for note in d.get("notes") or []:
        if note.get("resolvable") and not note.get("resolved"):
            unresolved += 1
            if not note.get("system"):
                actionable += 1
print(json.dumps({"verdict":"ok","verb":"review-threads","provider":"gitlab","data":{"unresolved":unresolved,"actionable":actionable}}))
PY
)"
    ;;

  merge)
    number="$(kv number "")"
    [[ -n "$number" ]] || fail_json "missing-pr-number"
    if mock_fixture "merge-$FIXTURE"; then exit 0; fi
    tmp="$(mktemp)"
    echo '{"merge_when_pipeline_succeeds":false,"should_remove_source_branch":false}' > "$tmp"
    resp="$(http_put "$API_BASE/projects/$PROJECT/merge_requests/$number/merge" "$tmp")" || fail_json "transport-failed"
    rm -f "$tmp"
    body="$(parse_transport_body "$resp")"
    emit "$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(json.dumps({'verdict':'ok','verb':'merge','provider':'gitlab','data':d}))" "$body")"
    ;;

  *)
    degraded_json "capability-missing"
    ;;
esac
