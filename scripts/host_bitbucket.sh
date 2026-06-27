#!/usr/bin/env bash
# Bitbucket host adapter — REST pull requests (PRD 026 Phase 4).
#
# Usage: host_bitbucket.sh --root PATH <verb> [--key value ...]
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
PROVIDER="bitbucket"

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
from host_lib import bitbucket_api_base, host_section, load_workflow_config, parse_owner_repo, resolve_provider, resolve_token_env

root = Path(sys.argv[1])
resolved = resolve_provider(root)
cfg = load_workflow_config(root)
host = host_section(cfg)
remote_url = resolved.get("remoteUrl")
slug = parse_owner_repo(remote_url)
owner, repo = slug if slug else ("", "")
print(json.dumps({
    "provider": "bitbucket",
    "tokenEnv": resolve_token_env(host, "bitbucket"),
    "apiBase": bitbucket_api_base(host),
    "owner": owner,
    "repo": repo,
    "nameWithOwner": f"{owner}/{repo}" if owner and repo else "",
    "degraded": resolved.get("degraded", False),
    "degradedReason": resolved.get("degradedReason"),
}))
PY
}

CTX="$(context_json)"
OWNER="$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['owner'])" "$CTX")"
REPO="$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['repo'])" "$CTX")"
API_BASE="$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('apiBase','https://api.bitbucket.org/2.0'))" "$CTX")"
TOKEN_ENV="$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('tokenEnv','BITBUCKET_TOKEN'))" "$CTX")"
REPO_PATH="repositories/$OWNER/$REPO"

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

parse_transport_body() {
  python3 -c 'import json,sys; d=json.load(sys.stdin); b=d.get("body") or ""; print(b if isinstance(b,str) else json.dumps(b))' <<<"$1"
}

bb_state_filter() {
  case "$1" in
    open) echo "OPEN" ;;
    closed) echo "DECLINED" ;;
    merged) echo "MERGED" ;;
    all) echo "" ;;
    *) echo "OPEN" ;;
  esac
}

bb_pr_to_view() {
  python3 - "$1" <<'PY'
import json, sys
pr = json.loads(sys.argv[1])
state = (pr.get("state") or "").upper()
src = pr.get("source") or {}
dst = pr.get("destination") or {}
src_branch = (src.get("branch") or {}).get("name")
dst_branch = (dst.get("branch") or {}).get("name")
head_sha = (src.get("commit") or {}).get("hash")
url = ((pr.get("links") or {}).get("html") or {}).get("href")
print(json.dumps({
    "number": pr.get("id"),
    "url": url,
    "headRefName": src_branch,
    "headRefOid": head_sha,
    "baseRefName": dst_branch,
    "state": state,
    "isDraft": False,
    "mergeable": "UNKNOWN",
    "mergeStateStatus": "UNKNOWN",
    "title": pr.get("title"),
    "body": pr.get("description"),
    "mergedAt": pr.get("closed_on") if state == "MERGED" else None,
    "mergeCommit": None,
}))
PY
}

case "$VERB" in
  repo-meta)
    if mock_fixture "repo-meta-$FIXTURE"; then exit 0; fi
    [[ -n "$OWNER" && -n "$REPO" ]] || fail_json "missing-repo"
    resp="$(http_get "$API_BASE/$REPO_PATH")" || fail_json "transport-failed"
    body="$(parse_transport_body "$resp")"
    emit "$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); ws=d.get('workspace') or {}; mb=d.get('mainbranch') or {}; print(json.dumps({'verdict':'ok','verb':'repo-meta','provider':'bitbucket','data':{'nameWithOwner':d.get('full_name'),'defaultBranch':mb.get('name'),'owner':ws.get('slug') or ws.get('name'),'name':d.get('name')}}))" "$body")"
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
    state="$(bb_state_filter "$(kv state open)")"
    limit="$(kv limit 30)"
    if mock_fixture "pr-list-$FIXTURE"; then exit 0; fi
    [[ -n "$OWNER" && -n "$REPO" ]] || fail_json "missing-repo"
    url="$API_BASE/$REPO_PATH/pullrequests?pagelen=$limit"
    [[ -n "$state" ]] && url="${url}&state=$state"
    q_parts=()
    [[ -n "$head" ]] && q_parts+=("source.branch.name=\"$head\"")
    [[ -n "$base" ]] && q_parts+=("destination.branch.name=\"$base\"")
    if [[ ${#q_parts[@]} -gt 0 ]]; then
      q="$(IFS=' AND '; echo "${q_parts[*]}")"
      url="${url}&q=$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))' "$q")"
    fi
    resp="$(http_get "$url")" || fail_json "transport-failed"
    body="$(parse_transport_body "$resp")"
    emit "$(python3 - "$body" <<'PY'
import json, sys
data = json.loads(sys.argv[1])
items = data.get("values") if isinstance(data, dict) else data
if not isinstance(items, list):
    items = []
out = []
for pr in items:
    src = pr.get("source") or {}
    dst = pr.get("destination") or {}
    out.append({
        "number": pr.get("id"),
        "url": ((pr.get("links") or {}).get("html") or {}).get("href"),
        "headRefName": (src.get("branch") or {}).get("name"),
        "headRefOid": (src.get("commit") or {}).get("hash"),
        "baseRefName": (dst.get("branch") or {}).get("name"),
        "state": (pr.get("state") or "").upper(),
        "title": pr.get("title"),
        "body": pr.get("description"),
    })
print(json.dumps({"verdict":"ok","verb":"pr-list","provider":"bitbucket","data":out}))
PY
)"
    ;;

  pr-view)
    number="$(kv number "")"
    url_arg="$(kv url "")"
    if mock_fixture "pr-view-$FIXTURE"; then exit 0; fi
    [[ -n "$OWNER" && -n "$REPO" ]] || fail_json "missing-repo"
    if [[ -z "$number" && -n "$url_arg" ]]; then
      number="$(python3 -c "import re,sys; m=re.search(r'/pull-requests/(\\d+)', sys.argv[1]); print(m.group(1) if m else '')" "$url_arg")"
    fi
    [[ -n "$number" ]] || fail_json "missing-pr-number"
    resp="$(http_get "$API_BASE/$REPO_PATH/pullrequests/$number")" || fail_json "transport-failed"
    body="$(parse_transport_body "$resp")"
    view="$(bb_pr_to_view "$body")"
    emit "$(python3 -c "import json,sys; print(json.dumps({'verdict':'ok','verb':'pr-view','provider':'bitbucket','data':json.loads(sys.argv[1])}))" "$view")"
    ;;

  pr-head)
    number="$(kv number "")"
    if [[ -z "$number" ]]; then
      resolve="$(bash "$SCRIPT_DIR/host.sh" --root "$ROOT" resolve-pr-for-branch 2>/dev/null || true)"
      number="$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); items=d.get('data') or []; print(items[0]['number'] if items else '')" "$resolve" 2>/dev/null || true)"
    fi
    [[ -n "$number" ]] || fail_json "missing-pr-number"
    view_out="$(bash "$0" --root "$ROOT" pr-view --number "$number")"
    emit "$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(json.dumps({'verdict':'ok','verb':'pr-head','provider':'bitbucket','data':{'headRefOid':d['data'].get('headRefOid'),'number':d['data'].get('number')}}))" "$view_out")"
    ;;

  pr-create)
    title="$(kv title "")"
    body="$(kv body "")"
    head="$(kv head "")"
    base="$(kv base "")"
    [[ -n "$title" && -n "$head" && -n "$base" ]] || fail_json "missing-fields"
    if mock_fixture "pr-create-$FIXTURE"; then exit 0; fi
    [[ -n "$OWNER" && -n "$REPO" ]] || fail_json "missing-repo"
    tmp="$(mktemp)"
    python3 - "$title" "$body" "$head" "$base" > "$tmp" <<'PY'
import json, sys
title, body, head, base = sys.argv[1:5]
print(json.dumps({
    "title": title,
    "description": body,
    "source": {"branch": {"name": head}},
    "destination": {"branch": {"name": base}},
    "close_source_branch": False,
}))
PY
    resp="$(http_post "$API_BASE/$REPO_PATH/pullrequests" "$tmp")" || fail_json "transport-failed"
    rm -f "$tmp"
    pr_body="$(parse_transport_body "$resp")"
    view="$(bb_pr_to_view "$pr_body")"
    emit "$(python3 -c "import json,sys; print(json.dumps({'verdict':'ok','verb':'pr-create','provider':'bitbucket','data':json.loads(sys.argv[1])}))" "$view")"
    ;;

  pr-close)
    number="$(kv number "")"
    [[ -n "$number" ]] || fail_json "missing-pr-number"
    if mock_fixture "pr-close-$FIXTURE"; then exit 0; fi
    [[ -n "$OWNER" && -n "$REPO" ]] || fail_json "missing-repo"
    tmp_close="$(mktemp)"
    : > "$tmp_close"
    resp="$(http_post "$API_BASE/$REPO_PATH/pullrequests/$number/decline" "$tmp_close")" || fail_json "transport-failed"
    rm -f "$tmp_close"
    body="$(parse_transport_body "$resp")"
    view="$(bb_pr_to_view "$body")"
    emit "$(python3 -c "import json,sys; print(json.dumps({'verdict':'ok','verb':'pr-close','provider':'bitbucket','data':json.loads(sys.argv[1])}))" "$view")"
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
    [[ -n "$OWNER" && -n "$REPO" ]] || fail_json "missing-repo"
    resp="$(http_get "$API_BASE/$REPO_PATH/commit/$sha/statuses?pagelen=100")" || fail_json "transport-failed"
    body="$(parse_transport_body "$resp")"
    checks="$(python3 - "$body" <<'PY'
import json, sys
data = json.loads(sys.argv[1])
items = data.get("values") if isinstance(data, dict) else data
if not isinstance(items, list):
    items = []
out = []
for r in items:
    state = (r.get("state") or "").upper()
    if state in ("INPROGRESS", "PENDING"):
        norm = "IN_PROGRESS"
    elif state == "SUCCESSFUL":
        norm = "SUCCESS"
    elif state == "FAILED":
        norm = "FAILURE"
    else:
        norm = state or "PENDING"
    out.append({
        "name": r.get("name") or r.get("key") or "check",
        "state": norm,
        "bucket": "pass" if norm in ("SUCCESS", "SKIPPED", "NEUTRAL") else ("fail" if norm == "FAILURE" else "pending"),
        "link": r.get("url") or "",
        "workflow": "",
    })
print(json.dumps(out))
PY
)"
    emit "$(python3 -c "import json,sys; print(json.dumps({'verdict':'ok','verb':'checks','provider':'bitbucket','data':json.loads(sys.argv[1])}))" "$checks")"
    ;;

  review-threads)
    number="$(kv number "")"
    [[ -n "$number" ]] || fail_json "missing-pr-number"
    if mock_fixture "review-threads-$FIXTURE"; then exit 0; fi
    [[ -n "$OWNER" && -n "$REPO" ]] || fail_json "missing-repo"
    resp="$(http_get "$API_BASE/$REPO_PATH/pullrequests/$number/comments?pagelen=100")" || fail_json "transport-failed"
    body="$(parse_transport_body "$resp")"
    emit "$(python3 - "$body" <<'PY'
import json, sys
data = json.loads(sys.argv[1])
items = data.get("values") if isinstance(data, dict) else data
if not isinstance(items, list):
    items = []
unresolved = len([c for c in items if not c.get("deleted") and not c.get("inline")])
actionable = unresolved
print(json.dumps({"verdict":"ok","verb":"review-threads","provider":"bitbucket","data":{"unresolved":unresolved,"actionable":actionable}}))
PY
)"
    ;;

  merge)
    number="$(kv number "")"
    [[ -n "$number" ]] || fail_json "missing-pr-number"
    if mock_fixture "merge-$FIXTURE"; then exit 0; fi
    tmp="$(mktemp)"
    echo '{"type":"merge_commit","message":"merge via shipwright","close_source_branch":false}' > "$tmp"
    resp="$(http_post "$API_BASE/$REPO_PATH/pullrequests/$number/merge" "$tmp")" || fail_json "transport-failed"
    rm -f "$tmp"
    body="$(parse_transport_body "$resp")"
    emit "$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(json.dumps({'verdict':'ok','verb':'merge','provider':'bitbucket','data':d}))" "$body")"
    ;;

  *)
    degraded_json "capability-missing"
    ;;
esac
