"""Bitbucket host adapter — REST pull requests (PRD 026/042)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from _sw.host import _common as common  # noqa: E402
from _sw.host._shape import bitbucket_pr_to_list_entry, bitbucket_pr_to_view  # noqa: E402

PROVIDER = "bitbucket"


def dispatch(root: Path, verb: str, args: list[str]) -> tuple[dict[str, Any], int]:
    ctx = common.bitbucket_context(root)
    if not common.fixture_name() and ctx.get("degraded"):
        return common.degraded_json(verb, PROVIDER, str(ctx.get("degradedReason", "missing-token"))), 0
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
    repo_path = ctx["repoPath"]
    if not repo_path:
        return common.fail_json("repo-meta", PROVIDER, "missing-repo"), 30
    url = f"{ctx['apiBase']}/{repo_path}"
    transport = common.http_request(root=root, provider=PROVIDER, method="GET", url=url, token_env=ctx["tokenEnv"])
    if "body" not in transport:
        return common.fail_json("repo-meta", PROVIDER, "transport-failed"), 30
    body = json.loads(common.parse_transport_body(transport))
    ws = body.get("workspace") or {}
    mb = body.get("mainbranch") or {}
    data = {
        "nameWithOwner": body.get("full_name"),
        "defaultBranch": mb.get("name"),
        "owner": ws.get("slug") or ws.get("name"),
        "name": body.get("name"),
    }
    return common.emit_verb_ok("repo-meta", PROVIDER, data), 0


def _resolve_pr_for_branch(root: Path, ctx: dict[str, Any], args: list[str]) -> tuple[dict[str, Any], int]:
    branch = common.kv_get(args, "branch", common.git_branch(root))
    if not branch:
        return common.fail_json("resolve-pr-for-branch", PROVIDER, "no-branch"), 30
    return _pr_list(root, ctx, ["--head", branch, "--state", "open", *args])


def _pr_list(root: Path, ctx: dict[str, Any], args: list[str]) -> tuple[dict[str, Any], int]:
    mocked = common.mock_fixture(root, f"pr-list-{common.fixture_name()}")
    if mocked:
        return mocked, 0
    repo_path = ctx["repoPath"]
    if not repo_path:
        return common.fail_json("pr-list", PROVIDER, "missing-repo"), 30
    head = common.kv_get(args, "head")
    base = common.kv_get(args, "base")
    state = common.bb_state_filter(common.kv_get(args, "state", "open"))
    limit = common.kv_get(args, "limit", "30")
    url = f"{ctx['apiBase']}/{repo_path}/pullrequests?pagelen={limit}"
    if state:
        url += f"&state={state}"
    q_parts: list[str] = []
    if head:
        q_parts.append(f'source.branch.name="{head}"')
    if base:
        q_parts.append(f'destination.branch.name="{base}"')
    if q_parts:
        url += f"&q={common.quote_bitbucket_q(' AND '.join(q_parts))}"
    transport = common.http_request(root=root, provider=PROVIDER, method="GET", url=url, token_env=ctx["tokenEnv"])
    if "body" not in transport:
        return common.fail_json("pr-list", PROVIDER, "transport-failed"), 30
    data = json.loads(common.parse_transport_body(transport))
    items = data.get("values") if isinstance(data, dict) else data
    if not isinstance(items, list):
        items = []
    return common.emit_verb_ok("pr-list", PROVIDER, [bitbucket_pr_to_list_entry(pr) for pr in items]), 0


def _pr_view(root: Path, ctx: dict[str, Any], args: list[str]) -> tuple[dict[str, Any], int]:
    mocked = common.mock_fixture(root, f"pr-view-{common.fixture_name()}")
    if mocked:
        return mocked, 0
    repo_path = ctx["repoPath"]
    if not repo_path:
        return common.fail_json("pr-view", PROVIDER, "missing-repo"), 30
    number = common.kv_get(args, "number")
    url_arg = common.kv_get(args, "url")
    if not number and url_arg:
        number = common.pr_number_from_url(url_arg, r"/pull-requests/(\d+)")
    if not number:
        return common.fail_json("pr-view", PROVIDER, "missing-pr-number"), 30
    url = f"{ctx['apiBase']}/{repo_path}/pullrequests/{number}"
    transport = common.http_request(root=root, provider=PROVIDER, method="GET", url=url, token_env=ctx["tokenEnv"])
    if "body" not in transport:
        return common.fail_json("pr-view", PROVIDER, "transport-failed"), 30
    return common.emit_verb_ok("pr-view", PROVIDER, bitbucket_pr_to_view(json.loads(common.parse_transport_body(transport)))), 0


def _pr_head(root: Path, ctx: dict[str, Any], args: list[str]) -> tuple[dict[str, Any], int]:
    number = common.kv_get(args, "number")
    if not number:
        listed, _ = _resolve_pr_for_branch(root, ctx, args)
        items = listed.get("data") or []
        number = str(items[0]["number"]) if items else ""
    if not number:
        return common.fail_json("pr-head", PROVIDER, "missing-pr-number"), 30
    viewed, code = _pr_view(root, ctx, ["--number", number])
    if code != 0:
        return viewed, code
    data = viewed["data"]
    return common.emit_verb_ok("pr-head", PROVIDER, {"headRefOid": data.get("headRefOid"), "number": data.get("number")}), 0


def _pr_create(root: Path, ctx: dict[str, Any], args: list[str]) -> tuple[dict[str, Any], int]:
    title = common.kv_get(args, "title")
    body_text = common.kv_get(args, "body")
    head = common.kv_get(args, "head")
    base = common.kv_get(args, "base")
    if not title or not head or not base:
        return common.fail_json("pr-create", PROVIDER, "missing-fields"), 30
    mocked = common.mock_fixture(root, f"pr-create-{common.fixture_name()}")
    if mocked:
        return mocked, 0
    repo_path = ctx["repoPath"]
    payload = json.dumps({
        "title": title,
        "description": body_text,
        "source": {"branch": {"name": head}},
        "destination": {"branch": {"name": base}},
        "close_source_branch": False,
    })
    url = f"{ctx['apiBase']}/{repo_path}/pullrequests"
    transport = common.http_request(root=root, provider=PROVIDER, method="POST", url=url, token_env=ctx["tokenEnv"], body=payload.encode())
    if "body" not in transport:
        return common.fail_json("pr-create", PROVIDER, "transport-failed"), 30
    return common.emit_verb_ok("pr-create", PROVIDER, bitbucket_pr_to_view(json.loads(common.parse_transport_body(transport)))), 0


def _pr_close(root: Path, ctx: dict[str, Any], args: list[str]) -> tuple[dict[str, Any], int]:
    number = common.kv_get(args, "number")
    if not number:
        return common.fail_json("pr-close", PROVIDER, "missing-pr-number"), 30
    mocked = common.mock_fixture(root, f"pr-close-{common.fixture_name()}")
    if mocked:
        return mocked, 0
    repo_path = ctx["repoPath"]
    url = f"{ctx['apiBase']}/{repo_path}/pullrequests/{number}/decline"
    transport = common.http_request(root=root, provider=PROVIDER, method="POST", url=url, token_env=ctx["tokenEnv"], body=b"{}")
    if "body" not in transport:
        return common.fail_json("pr-close", PROVIDER, "transport-failed"), 30
    return common.emit_verb_ok("pr-close", PROVIDER, bitbucket_pr_to_view(json.loads(common.parse_transport_body(transport)))), 0


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
    repo_path = ctx["repoPath"]
    url = f"{ctx['apiBase']}/{repo_path}/commit/{sha}/statuses?pagelen=100"
    transport = common.http_request(root=root, provider=PROVIDER, method="GET", url=url, token_env=ctx["tokenEnv"])
    if "body" not in transport:
        return common.fail_json("checks", PROVIDER, "transport-failed"), 30
    return common.emit_verb_ok("checks", PROVIDER, common.map_bitbucket_checks(common.parse_transport_body(transport))), 0


def _review_threads(root: Path, ctx: dict[str, Any], args: list[str]) -> tuple[dict[str, Any], int]:
    number = common.kv_get(args, "number")
    if not number:
        return common.fail_json("review-threads", PROVIDER, "missing-pr-number"), 30
    mocked = common.mock_fixture(root, f"review-threads-{common.fixture_name()}")
    if mocked:
        return mocked, 0
    repo_path = ctx["repoPath"]
    url = f"{ctx['apiBase']}/{repo_path}/pullrequests/{number}/comments?pagelen=100"
    transport = common.http_request(root=root, provider=PROVIDER, method="GET", url=url, token_env=ctx["tokenEnv"])
    if "body" not in transport:
        return common.fail_json("review-threads", PROVIDER, "transport-failed"), 30
    data = json.loads(common.parse_transport_body(transport))
    items = data.get("values") if isinstance(data, dict) else data
    if not isinstance(items, list):
        items = []
    unresolved = len([c for c in items if not c.get("deleted") and not c.get("inline")])
    return common.emit_verb_ok("review-threads", PROVIDER, {"unresolved": unresolved, "actionable": unresolved}), 0


def _merge(root: Path, ctx: dict[str, Any], args: list[str]) -> tuple[dict[str, Any], int]:
    number = common.kv_get(args, "number")
    if not number:
        return common.fail_json("merge", PROVIDER, "missing-pr-number"), 30
    mocked = common.mock_fixture(root, f"merge-{common.fixture_name()}")
    if mocked:
        return mocked, 0
    repo_path = ctx["repoPath"]
    url = f"{ctx['apiBase']}/{repo_path}/pullrequests/{number}/merge"
    body = b'{"type":"merge_commit","message":"merge via shipwright","close_source_branch":false}'
    transport = common.http_request(root=root, provider=PROVIDER, method="POST", url=url, token_env=ctx["tokenEnv"], body=body)
    if "body" not in transport:
        return common.fail_json("merge", PROVIDER, "transport-failed"), 30
    return common.emit_verb_ok("merge", PROVIDER, json.loads(common.parse_transport_body(transport))), 0

def _remote_ref_exists(root: Path, ctx: dict[str, Any], args: list[str]) -> tuple[dict[str, Any], int]:
    branch = common.kv_get(args, "branch")
    if not branch:
        return common.fail_json("remote-ref-exists", PROVIDER, "missing-branch"), 30
    mocked = common.mock_fixture(root, f"remote-ref-exists-{common.fixture_name()}")
    if mocked:
        return mocked, 0
    workspace, repo = ctx.get("workspace"), ctx.get("repo")
    if not workspace or not repo:
        return common.fail_json("remote-ref-exists", PROVIDER, "missing-repo"), 30
    from urllib.parse import quote
    url = f"{ctx['apiBase']}/repositories/{workspace}/{repo}/refs/branches/{quote(branch, safe='')}"
    transport = common.http_request(root=root, provider=PROVIDER, method="GET", url=url, token_env=ctx["tokenEnv"])
    return common.remote_ref_exists_from_transport(verb="remote-ref-exists", provider=PROVIDER, branch=branch, transport=transport)


