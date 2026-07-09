"""GitHub host adapter — REST + GraphQL verbs (PRD 026/042)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from _sw.host import _common as common  # noqa: E402
from _sw.host._shape import github_pr_to_list_entry, github_pr_to_view  # noqa: E402

PROVIDER = "github"


def dispatch(root: Path, verb: str, args: list[str]) -> tuple[dict[str, Any], int]:
    """Run a host verb; return (payload, exit_code)."""
    ctx = common.github_context(root)
    if not common.fixture_name() and ctx.get("degraded"):
        payload = common.degraded_json(verb, PROVIDER, str(ctx.get("degradedReason", "missing-token")))
        return payload, 0

    handlers = {
        "repo-meta": _repo_meta,
        "resolve-pr-for-branch": _resolve_pr_for_branch,
        "pr-list": _pr_list,
        "pr-view": _pr_view,
        "pr-head": _pr_head,
        "pr-create": _pr_create,
        "pr-close": _pr_close,
        "checks": _checks,
        "review-threads": _review_threads,
        "merge": _merge,
        "remote-ref-exists": _remote_ref_exists,
    }
    handler = handlers.get(verb)
    if handler is None:
        return common.degraded_json(verb, PROVIDER, "capability-missing"), 0
    return handler(root, ctx, args)


def _repo_meta(root: Path, ctx: dict[str, Any], args: list[str]) -> tuple[dict[str, Any], int]:
    mocked = common.mock_fixture(root, f"repo-meta-{common.fixture_name()}")
    if mocked:
        return mocked, 0
    owner, repo = ctx["owner"], ctx["repo"]
    if not owner or not repo:
        return common.fail_json("repo-meta", PROVIDER, "missing-repo"), 30
    url = f"{ctx['apiBase']}/repos/{owner}/{repo}"
    transport = common.http_request(root=root, provider=PROVIDER, method="GET", url=url, token_env=ctx["tokenEnv"])
    if transport.get("verdict") not in ("ok",) and "body" not in transport:
        return common.fail_json("repo-meta", PROVIDER, "transport-failed"), 30
    body = json.loads(common.parse_transport_body(transport))
    data = {
        "nameWithOwner": body.get("full_name") or body.get("name"),
        "defaultBranch": body.get("default_branch"),
        "owner": (body.get("owner") or {}).get("login"),
        "name": body.get("name"),
    }
    return common.emit_verb_ok("repo-meta", PROVIDER, data), 0


def _resolve_pr_for_branch(root: Path, ctx: dict[str, Any], args: list[str]) -> tuple[dict[str, Any], int]:
    branch = common.kv_get(args, "branch", common.git_branch(root))
    if not branch:
        return common.fail_json("resolve-pr-for-branch", PROVIDER, "no-branch"), 30
    new_args = ["--head", branch, "--state", "open", *args]
    return _pr_list(root, ctx, new_args)


def _pr_list(root: Path, ctx: dict[str, Any], args: list[str]) -> tuple[dict[str, Any], int]:
    mocked = common.mock_fixture(root, f"pr-list-{common.fixture_name()}")
    if mocked:
        return mocked, 0
    owner, repo = ctx["owner"], ctx["repo"]
    if not owner or not repo:
        return common.fail_json("pr-list", PROVIDER, "missing-repo"), 30
    head = common.kv_get(args, "head")
    base = common.kv_get(args, "base")
    state = common.kv_get(args, "state", "open")
    limit = common.kv_get(args, "limit", "30")
    url = f"{ctx['apiBase']}/repos/{owner}/{repo}/pulls?state={state}&per_page={limit}"
    if head:
        url += f"&head={owner}:{head}"
    if base:
        url += f"&base={base}"
    transport = common.http_request(root=root, provider=PROVIDER, method="GET", url=url, token_env=ctx["tokenEnv"])
    if "body" not in transport and transport.get("verdict") != "ok":
        return common.fail_json("pr-list", PROVIDER, "transport-failed"), 30
    items = json.loads(common.parse_transport_body(transport))
    if not isinstance(items, list):
        items = []
    data = [github_pr_to_list_entry(pr) for pr in items]
    return common.emit_verb_ok("pr-list", PROVIDER, data), 0


def _pr_view(root: Path, ctx: dict[str, Any], args: list[str]) -> tuple[dict[str, Any], int]:
    mocked = common.mock_fixture(root, f"pr-view-{common.fixture_name()}")
    if mocked:
        return mocked, 0
    owner, repo = ctx["owner"], ctx["repo"]
    if not owner or not repo:
        return common.fail_json("pr-view", PROVIDER, "missing-repo"), 30
    number = common.kv_get(args, "number")
    url_arg = common.kv_get(args, "url")
    if not number and url_arg:
        number = common.pr_number_from_url(url_arg, r"/pull/(\d+)")
    if not number:
        return common.fail_json("pr-view", PROVIDER, "missing-pr-number"), 30
    url = f"{ctx['apiBase']}/repos/{owner}/{repo}/pulls/{number}"
    transport = common.http_request(root=root, provider=PROVIDER, method="GET", url=url, token_env=ctx["tokenEnv"])
    if "body" not in transport and transport.get("verdict") != "ok":
        return common.fail_json("pr-view", PROVIDER, "transport-failed"), 30
    view = github_pr_to_view(json.loads(common.parse_transport_body(transport)))
    return common.emit_verb_ok("pr-view", PROVIDER, view), 0


def _pr_head(root: Path, ctx: dict[str, Any], args: list[str]) -> tuple[dict[str, Any], int]:
    number = common.kv_get(args, "number")
    if not number:
        listed, _ = _resolve_pr_for_branch(root, ctx, args)
        items = listed.get("data") or []
        number = str(items[0]["number"]) if items else ""
    if not number:
        return common.fail_json("pr-head", PROVIDER, "missing-pr-number"), 30
    viewed, code = _pr_view(root, ctx, ["--number", number])
    if code != 0 or viewed.get("verdict") != "ok":
        return viewed, code
    data = viewed["data"]
    return common.emit_verb_ok(
        "pr-head", PROVIDER, {"headRefOid": data.get("headRefOid"), "number": data.get("number")}
    ), 0


def _pr_create(root: Path, ctx: dict[str, Any], args: list[str]) -> tuple[dict[str, Any], int]:
    title = common.kv_get(args, "title")
    body = common.kv_get(args, "body")
    head = common.kv_get(args, "head")
    base = common.kv_get(args, "base")
    draft = common.kv_get(args, "draft", "false")
    if not title or not head or not base:
        return common.fail_json("pr-create", PROVIDER, "missing-fields"), 30
    mocked = common.mock_fixture(root, f"pr-create-{common.fixture_name()}")
    if mocked:
        return mocked, 0
    owner, repo = ctx["owner"], ctx["repo"]
    if not owner or not repo:
        return common.fail_json("pr-create", PROVIDER, "missing-repo"), 30
    payload = json.dumps({"title": title, "body": body, "head": head, "base": base, "draft": draft == "true"})
    url = f"{ctx['apiBase']}/repos/{owner}/{repo}/pulls"
    transport = common.http_request(
        root=root, provider=PROVIDER, method="POST", url=url, token_env=ctx["tokenEnv"], body=payload.encode()
    )
    if "body" not in transport and transport.get("verdict") != "ok":
        return common.fail_json("pr-create", PROVIDER, "transport-failed"), 30
    view = github_pr_to_view(json.loads(common.parse_transport_body(transport)))
    return common.emit_verb_ok("pr-create", PROVIDER, view), 0


def _checks(root: Path, ctx: dict[str, Any], args: list[str]) -> tuple[dict[str, Any], int]:
    sha = common.kv_get(args, "sha")
    number = common.kv_get(args, "number")
    if not sha and number:
        viewed, _ = _pr_view(root, ctx, ["--number", number])
        sha = str((viewed.get("data") or {}).get("headRefOid") or "")
    if not sha:
        return common.fail_json("checks", PROVIDER, "missing-sha"), 30
    mocked = common.mock_fixture(root, f"checks-{common.fixture_name()}")
    if mocked:
        return mocked, 0
    owner, repo = ctx["owner"], ctx["repo"]
    if not owner or not repo:
        return common.fail_json("checks", PROVIDER, "missing-repo"), 30
    url = f"{ctx['apiBase']}/repos/{owner}/{repo}/commits/{sha}/check-runs?per_page=100"
    transport = common.http_request(root=root, provider=PROVIDER, method="GET", url=url, token_env=ctx["tokenEnv"])
    if "body" not in transport and transport.get("verdict") != "ok":
        return common.fail_json("checks", PROVIDER, "transport-failed"), 30
    checks = common.map_github_checks(common.parse_transport_body(transport))
    return common.emit_verb_ok("checks", PROVIDER, checks), 0


def _review_threads(root: Path, ctx: dict[str, Any], args: list[str]) -> tuple[dict[str, Any], int]:
    number = common.kv_get(args, "number")
    if not number:
        return common.fail_json("review-threads", PROVIDER, "missing-pr-number"), 30
    mocked = common.mock_fixture(root, f"review-threads-{common.fixture_name()}")
    if mocked:
        return mocked, 0
    owner, repo = ctx["owner"], ctx["repo"]
    if not owner or not repo:
        return common.fail_json("review-threads", PROVIDER, "missing-repo"), 30
    unresolved = actionable = 0
    cursor = ""
    pages = 0
    query = (
        "query($o:String!,$r:String!,$p:Int!,$c:String){repository(owner:$o,name:$r)"
        "{pullRequest(number:$p){reviewThreads(first:100,after:$c)"
        "{pageInfo{hasNextPage endCursor} nodes{isResolved isOutdated}}}}}}"
    )
    while pages < 20:
        gql = json.dumps({"query": query, "variables": {"o": owner, "r": repo, "p": int(number), "c": cursor}})
        url = f"{ctx['apiBase']}/graphql"
        transport = common.http_request(
            root=root, provider=PROVIDER, method="POST", url=url, token_env=ctx["tokenEnv"], body=gql.encode()
        )
        if "body" not in transport:
            return common.fail_json("review-threads", PROVIDER, "transport-failed"), 30
        page_data = json.loads(common.parse_transport_body(transport))
        rt = (
            ((page_data.get("data") or {}).get("repository") or {}).get("pullRequest") or {}
        ).get("reviewThreads") or {}
        nodes = rt.get("nodes") or []
        pi = rt.get("pageInfo") or {}
        unresolved += len([n for n in nodes if not n.get("isResolved")])
        actionable += len([n for n in nodes if not n.get("isResolved") and not n.get("isOutdated")])
        if not pi.get("hasNextPage") or not pi.get("endCursor"):
            break
        cursor = str(pi.get("endCursor") or "")
        pages += 1
    return common.emit_verb_ok("review-threads", PROVIDER, {"unresolved": unresolved, "actionable": actionable}), 0


def _pr_close(root: Path, ctx: dict[str, Any], args: list[str]) -> tuple[dict[str, Any], int]:
    number = common.kv_get(args, "number")
    if not number:
        return common.fail_json("pr-close", PROVIDER, "missing-pr-number"), 30
    mocked = common.mock_fixture(root, f"pr-close-{common.fixture_name()}")
    if mocked:
        return mocked, 0
    owner, repo = ctx["owner"], ctx["repo"]
    if not owner or not repo:
        return common.fail_json("pr-close", PROVIDER, "missing-repo"), 30
    url = f"{ctx['apiBase']}/repos/{owner}/{repo}/pulls/{number}"
    transport = common.http_request(
        root=root,
        provider=PROVIDER,
        method="PATCH",
        url=url,
        token_env=ctx["tokenEnv"],
        body=b'{"state":"closed"}',
    )
    if "body" not in transport and transport.get("verdict") != "ok":
        return common.fail_json("pr-close", PROVIDER, "transport-failed"), 30
    view = github_pr_to_view(json.loads(common.parse_transport_body(transport)))
    return common.emit_verb_ok("pr-close", PROVIDER, view), 0


def _merge(root: Path, ctx: dict[str, Any], args: list[str]) -> tuple[dict[str, Any], int]:
    number = common.kv_get(args, "number")
    method = common.kv_get(args, "method", "squash")
    if not number:
        return common.fail_json("merge", PROVIDER, "missing-pr-number"), 30
    mocked = common.mock_fixture(root, f"merge-{common.fixture_name()}")
    if mocked:
        return mocked, 0
    owner, repo = ctx["owner"], ctx["repo"]
    url = f"{ctx['apiBase']}/repos/{owner}/{repo}/pulls/{number}/merge"
    transport = common.http_request(
        root=root,
        provider=PROVIDER,
        method="PUT",
        url=url,
        token_env=ctx["tokenEnv"],
        body=json.dumps({"merge_method": method}).encode(),
    )
    if "body" not in transport and transport.get("verdict") != "ok":
        return common.fail_json("merge", PROVIDER, "transport-failed"), 30
    data = json.loads(common.parse_transport_body(transport))
    return common.emit_verb_ok("merge", PROVIDER, data), 0

def _remote_ref_exists(root: Path, ctx: dict[str, Any], args: list[str]) -> tuple[dict[str, Any], int]:
    branch = common.kv_get(args, "branch")
    if not branch:
        return common.fail_json("remote-ref-exists", PROVIDER, "missing-branch"), 30
    mocked = common.mock_fixture(root, f"remote-ref-exists-{common.fixture_name()}")
    if mocked:
        return mocked, 0
    owner, repo = ctx.get("owner"), ctx.get("repo")
    if not owner or not repo:
        return common.fail_json("remote-ref-exists", PROVIDER, "missing-repo"), 30
    url = f"{ctx['apiBase']}/repos/{owner}/{repo}/git/ref/heads/{branch}"
    transport = common.http_request(root=root, provider=PROVIDER, method="GET", url=url, token_env=ctx["tokenEnv"])
    return common.remote_ref_exists_from_transport(verb="remote-ref-exists", provider=PROVIDER, branch=branch, transport=transport)


