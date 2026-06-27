#!/usr/bin/env bash
# GitHub host adapter — REST + GraphQL verbs (PRD 026 Phase 2).
#
# Usage: host_github.sh --root PATH <verb> [--key value ...]
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
from host_lib import github_api_base, host_section, load_workflow_config, parse_owner_repo, resolve_provider, resolve_token_env

root = Path(sys.argv[1])
resolved = resolve_provider(root)
cfg = load_workflow_config(root)
host = host_section(cfg)
remote_url = resolved.get("remoteUrl")
slug = parse_owner_repo(remote_url)
owner, repo = slug if slug else ("", "")
print(json.dumps({
    "provider": resolved.get("provider", "github"),
    "tokenEnv": resolve_token_env(host, "github"),
    "apiBase": github_api_base(host),
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
API_BASE="$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('apiBase','https://api.github.com'))" "$CTX")"
TOKEN_ENV="$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('tokenEnv','GITHUB_TOKEN'))" "$CTX")"

emit() {
  python3 -c 'import json,sys; print(json.dumps(json.loads(sys.argv[1]), indent=2))' "$1"
}

emit_verb_ok() {
  local verb="$1"
  local data_json="$2"
  VERB_OUT="$verb" DATA_JSON="$data_json" python3 -c '
import json, os
print(json.dumps({"verdict": "ok", "verb": os.environ["VERB_OUT"], "provider": "github", "data": json.loads(os.environ["DATA_JSON"])}, indent=2))
'
}


fail_json() {
  local reason="$1" msg="${2:-}"
  emit "{\"verdict\":\"fail\",\"verb\":\"$VERB\",\"provider\":\"github\",\"reason\":\"$reason\",\"message\":\"$msg\"}"
  exit 30
}

degraded_json() {
  local reason="$1"
  emit "{\"verdict\":\"degraded\",\"verb\":\"$VERB\",\"provider\":\"github\",\"reason\":\"$reason\",\"retryable\":false}"
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
  if [[ "$name" == repo-meta-* ]]; then
    f="$FIXTURE_DIR/repo-meta-green.json"
  elif [[ "$name" == pr-view-* ]]; then
    f="$FIXTURE_DIR/pr-view-green.json"
  elif [[ "$name" == pr-list-* ]]; then
    f="$FIXTURE_DIR/pr-list-green.json"
  elif [[ "$name" == pr-close-* ]]; then
    f="$FIXTURE_DIR/pr-close-green.json"
  else
    f=""
  fi
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
  "$TRANSPORT" --root "$ROOT" --provider github --method GET --url "$url" --token-env "$TOKEN_ENV"
}

http_post() {
  local url="$1" body_file="$2"
  "$TRANSPORT" --root "$ROOT" --provider github --method POST --url "$url" --token-env "$TOKEN_ENV" --body-file "$body_file"
}

http_put() {
  local url="$1" body_file="$2"
  "$TRANSPORT" --root "$ROOT" --provider github --method PUT --url "$url" --token-env "$TOKEN_ENV" --body-file "$body_file"
}

http_patch() {
  local url="$1" body_file="$2"
  "$TRANSPORT" --root "$ROOT" --provider github --method PATCH --url "$url" --token-env "$TOKEN_ENV" --body-file "$body_file"
}

parse_transport_body() {
  python3 -c 'import json,sys; d=json.load(sys.stdin); b=d.get("body") or ""; print(b if isinstance(b,str) else json.dumps(b))' <<<"$1"
}

gh_pr_to_view() {
  python3 - "$1" <<'PY'
import json, sys
pr = json.loads(sys.argv[1])
head = pr.get("head") or {}
base = pr.get("base") or {}
user = head.get("user") or {}
print(json.dumps({
    "number": pr.get("number"),
    "url": pr.get("html_url"),
    "headRefName": head.get("ref"),
    "headRefOid": head.get("sha"),
    "baseRefName": base.get("ref"),
    "state": "MERGED" if pr.get("merged") else pr.get("state", "").upper(),
    "isDraft": pr.get("draft", False),
    "mergeable": "CONFLICTING" if pr.get("mergeable") is False else ("MERGEABLE" if pr.get("mergeable") is True else "UNKNOWN"),
    "mergeStateStatus": pr.get("mergeable_state", "UNKNOWN").upper() if pr.get("mergeable_state") else "UNKNOWN",
    "title": pr.get("title"),
    "body": pr.get("body"),
    "mergedAt": pr.get("merged_at"),
    "mergeCommit": {"oid": (pr.get("merge_commit_sha") or "")} if pr.get("merge_commit_sha") else None,
}))
PY
}

map_checks() {
  python3 - "$1" <<'PY'
import json, sys
data = json.loads(sys.argv[1])
runs = data.get("check_runs") or []
out = []
for r in runs:
    status = (r.get("status") or "").upper()
    conclusion = (r.get("conclusion") or "").upper()
    if status in ("QUEUED", "IN_PROGRESS", "PENDING"):
        state = "IN_PROGRESS"
    elif conclusion == "SUCCESS" or (status == "COMPLETED" and conclusion in ("SUCCESS", "NEUTRAL", "SKIPPED")):
        state = "SUCCESS" if conclusion != "NEUTRAL" else "NEUTRAL"
    elif conclusion in ("FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED"):
        state = "FAILURE"
    else:
        state = conclusion or status or "PENDING"
    out.append({
        "name": r.get("name") or "check",
        "state": state,
        "bucket": "pass" if state in ("SUCCESS", "SKIPPED", "NEUTRAL") else ("fail" if state == "FAILURE" else "pending"),
        "link": (r.get("html_url") or ""),
        "workflow": (r.get("app") or {}).get("slug") or "",
    })
print(json.dumps(out))
PY
}

case "$VERB" in
  repo-meta)
    if mock_fixture "repo-meta-$FIXTURE"; then exit 0; fi
    [[ -n "$OWNER" && -n "$REPO" ]] || fail_json "missing-repo"
    resp="$(http_get "$API_BASE/repos/$OWNER/$REPO")" || fail_json "transport-failed"
    body="$(parse_transport_body "$resp")"
    meta_data="$(BODY="$body" python3 -c 'import json,os; d=json.loads(os.environ["BODY"]); print(json.dumps({"nameWithOwner": d.get("full_name") or d.get("name"), "defaultBranch": d.get("default_branch"), "owner": (d.get("owner") or {}).get("login"), "name": d.get("name")}))' )"
    emit_verb_ok repo-meta "$meta_data"
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
    state="$(kv state open)"
    limit="$(kv limit 30)"
    if mock_fixture "pr-list-$FIXTURE"; then exit 0; fi
    [[ -n "$OWNER" && -n "$REPO" ]] || fail_json "missing-repo"
    url="$API_BASE/repos/$OWNER/$REPO/pulls?state=$state&per_page=$limit"
    [[ -n "$head" ]] && url="${url}&head=${OWNER}:${head}"
    [[ -n "$base" ]] && url="${url}&base=${base}"
    resp="$(http_get "$url")" || fail_json "transport-failed"
    body="$(parse_transport_body "$resp")"
    emit "$(python3 - "$body" <<'PY'
import json, sys
items = json.loads(sys.argv[1])
if not isinstance(items, list):
    items = []
out = []
for pr in items:
    head = pr.get("head") or {}
    base = pr.get("base") or {}
    out.append({
        "number": pr.get("number"),
        "url": pr.get("html_url"),
        "headRefName": head.get("ref"),
        "headRefOid": head.get("sha"),
        "baseRefName": base.get("ref"),
        "state": pr.get("state", "").upper(),
        "title": pr.get("title"),
        "body": pr.get("body"),
    })
print(json.dumps({"verdict":"ok","verb":"pr-list","provider":"github","data":out}))
PY
)"
    ;;

  pr-view)
    number="$(kv number "")"
    url_arg="$(kv url "")"
    if mock_fixture "pr-view-$FIXTURE"; then exit 0; fi
    [[ -n "$OWNER" && -n "$REPO" ]] || fail_json "missing-repo"
    if [[ -z "$number" && -n "$url_arg" ]]; then
      number="$(python3 -c "import re,sys; m=re.search(r'/pull/(\d+)', sys.argv[1]); print(m.group(1) if m else '')" "$url_arg")"
    fi
    [[ -n "$number" ]] || fail_json "missing-pr-number"
    resp="$(http_get "$API_BASE/repos/$OWNER/$REPO/pulls/$number")" || fail_json "transport-failed"
    body="$(parse_transport_body "$resp")"
    view="$(gh_pr_to_view "$body")"
    payload="$(VIEW="$view" python3 -c 'import json,os; print(json.dumps({"verdict":"ok","verb":"pr-view","provider":"github","data":json.loads(os.environ["VIEW"])}))' )"
    emit "$payload"
    ;;

  pr-head)
    number="$(kv number "")"
    if [[ -z "$number" ]]; then
      resolve="$(bash "$SCRIPT_DIR/host.sh" --root "$ROOT" resolve-pr-for-branch 2>/dev/null || true)"
      number="$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); items=d.get('data') or []; print(items[0]['number'] if items else '')" "$resolve" 2>/dev/null || true)"
    fi
    [[ -n "$number" ]] || fail_json "missing-pr-number"
    view_out="$(bash "$0" --root "$ROOT" pr-view --number "$number")"
    head_data="$(VIEW="$view_out" python3 -c 'import json,os; d=json.loads(os.environ["VIEW"]); print(json.dumps({"headRefOid": d["data"].get("headRefOid"), "number": d["data"].get("number")}))' )"
    emit_verb_ok pr-head "$head_data"
    ;;

  pr-create)
    title="$(kv title "")"
    body="$(kv body "")"
    head="$(kv head "")"
    base="$(kv base "")"
    draft="$(kv draft false)"
    [[ -n "$title" && -n "$head" && -n "$base" ]] || fail_json "missing-fields"
    if mock_fixture "pr-create-$FIXTURE"; then exit 0; fi
    [[ -n "$OWNER" && -n "$REPO" ]] || fail_json "missing-repo"
    tmp="$(mktemp)"
    python3 - "$title" "$body" "$head" "$base" "$draft" > "$tmp" <<'PY'
import json, sys
title, body, head, base, draft = sys.argv[1:6]
print(json.dumps({"title": title, "body": body, "head": head, "base": base, "draft": draft == "true"}))
PY
    resp="$(http_post "$API_BASE/repos/$OWNER/$REPO/pulls" "$tmp")" || fail_json "transport-failed"
    rm -f "$tmp"
    pr_body="$(parse_transport_body "$resp")"
    view="$(gh_pr_to_view "$pr_body")"
    emit "$(python3 -c "import json,sys; print(json.dumps({'verdict':'ok','verb':'pr-create','provider':'github','data':json.loads(sys.argv[1])}))" "$view")"
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
    resp="$(http_get "$API_BASE/repos/$OWNER/$REPO/commits/$sha/check-runs?per_page=100")" || fail_json "transport-failed"
    body="$(parse_transport_body "$resp")"
    checks="$(map_checks "$body")"
    emit_verb_ok checks "$checks"
    ;;

  review-threads)
    number="$(kv number "")"
    [[ -n "$number" ]] || fail_json "missing-pr-number"
    if mock_fixture "review-threads-$FIXTURE"; then exit 0; fi
    [[ -n "$OWNER" && -n "$REPO" ]] || fail_json "missing-repo"
    unresolved=0
    actionable=0
    cursor=""
    pages=0
    while [[ $pages -lt 20 ]]; do
      gql_body="$(mktemp)"
      python3 - "$OWNER" "$REPO" "$number" "$cursor" > "$gql_body" <<'PY'
import json, sys
o, r, p, c = sys.argv[1:5]
query = '''query($o:String!,$r:String!,$p:Int!,$c:String){repository(owner:$o,name:$r){pullRequest(number:$p){reviewThreads(first:100,after:$c){pageInfo{hasNextPage endCursor} nodes{isResolved isOutdated}}}}}}'''
print(json.dumps({"query": query, "variables": {"o": o, "r": r, "p": int(p), "c": c}}))
PY
      resp="$(http_post "$API_BASE/graphql" "$gql_body")" || fail_json "transport-failed"
      rm -f "$gql_body"
      body="$(parse_transport_body "$resp")"
      page="$(python3 - "$body" <<'PY'
import json, sys
d = json.loads(sys.argv[1])
rt = (((d.get("data") or {}).get("repository") or {}).get("pullRequest") or {}).get("reviewThreads") or {}
nodes = rt.get("nodes") or []
pi = rt.get("pageInfo") or {}
u = len([n for n in nodes if not n.get("isResolved")])
a = len([n for n in nodes if not n.get("isResolved") and not n.get("isOutdated")])
print(json.dumps({"unresolved": u, "actionable": a, "hasNext": pi.get("hasNextPage"), "cursor": pi.get("endCursor") or ""}))
PY
)"
      unresolved=$((unresolved + $(python3 -c "import json,sys; print(json.loads(sys.argv[1])['unresolved'])" "$page")))
      actionable=$((actionable + $(python3 -c "import json,sys; print(json.loads(sys.argv[1])['actionable'])" "$page")))
      has_next="$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('hasNext'))" "$page")"
      cursor="$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('cursor',''))" "$page")"
      pages=$((pages + 1))
      [[ "$has_next" == "True" && -n "$cursor" ]] || break
    done
    emit "{\"verdict\":\"ok\",\"verb\":\"review-threads\",\"provider\":\"github\",\"data\":{\"unresolved\":$unresolved,\"actionable\":$actionable}}"
    ;;


  pr-close)
    number="$(kv number "")"
    [[ -n "$number" ]] || fail_json "missing-pr-number"
    if mock_fixture "pr-close-$FIXTURE"; then exit 0; fi
    [[ -n "$OWNER" && -n "$REPO" ]] || fail_json "missing-repo"
    tmp="$(mktemp)"
    echo '{"state":"closed"}' > "$tmp"
    resp="$(http_patch "$API_BASE/repos/$OWNER/$REPO/pulls/$number" "$tmp")" || fail_json "transport-failed"
    rm -f "$tmp"
    body="$(parse_transport_body "$resp")"
    view="$(gh_pr_to_view "$body")"
    emit "$(python3 -c "import json,sys; print(json.dumps({'verdict':'ok','verb':'pr-close','provider':'github','data':json.loads(sys.argv[1])}))" "$view")"
    ;;

  merge)
    number="$(kv number "")"
    method="$(kv method squash)"
    [[ -n "$number" ]] || fail_json "missing-pr-number"
    if mock_fixture "merge-$FIXTURE"; then exit 0; fi
    tmp="$(mktemp)"
    echo "{\"merge_method\":\"$method\"}" > "$tmp"
    resp="$(http_put "$API_BASE/repos/$OWNER/$REPO/pulls/$number/merge" "$tmp")" || fail_json "transport-failed"
    rm -f "$tmp"
    body="$(parse_transport_body "$resp")"
    emit "$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(json.dumps({'verdict':'ok','verb':'merge','provider':'github','data':d}))" "$body")"
    ;;

  *)
    degraded_json "capability-missing"
    ;;
esac
