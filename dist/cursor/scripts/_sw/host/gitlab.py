"""GitLab host adapter — REST merge requests (PRD 026/042)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from _sw.host import _common as common  # noqa: E402
from _sw.host._shape import gitlab_mr_to_list_entry, gitlab_mr_to_view  # noqa: E402

PROVIDER = "gitlab"


def dispatch(root: Path, verb: str, args: list[str]) -> tuple[dict[str, Any], int]:
    ctx = common.gitlab_context(root)
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
    project = ctx["project"]
    if not project:
        return common.fail_json("repo-meta", PROVIDER, "missing-repo"), 30
    url = f"{ctx['apiBase']}/projects/{project}"
    transport = common.http_request(root=root, provider=PROVIDER, method="GET", url=url, token_env=ctx["tokenEnv"])
    if "body" not in transport:
        return common.fail_json("repo-meta", PROVIDER, "transport-failed"), 30
    body = json.loads(common.parse_transport_body(transport))
    ns = body.get("namespace") or {}
    data = {
        "nameWithOwner": body.get("path_with_namespace"),
        "defaultBranch": body.get("default_branch"),
        "owner": ns.get("path") or ns.get("name"),
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
    project = ctx["project"]
    if not project:
        return common.fail_json("pr-list", PROVIDER, "missing-repo"), 30
    head = common.kv_get(args, "head")
    base = common.kv_get(args, "base")
    state = common.gl_state_filter(common.kv_get(args, "state", "open"))
    limit = common.kv_get(args, "limit", "30")
    url = f"{ctx['apiBase']}/projects/{project}/merge_requests?state={state}&per_page={limit}"
    if head:
        url += f"&source_branch={head}"
    if base:
        url += f"&target_branch={base}"
    transport = common.http_request(root=root, provider=PROVIDER, method="GET", url=url, token_env=ctx["tokenEnv"])
    if "body" not in transport:
        return common.fail_json("pr-list", PROVIDER, "transport-failed"), 30
    items = json.loads(common.parse_transport_body(transport))
    if not isinstance(items, list):
        items = []
    return common.emit_verb_ok("pr-list", PROVIDER, [gitlab_mr_to_list_entry(mr) for mr in items]), 0


def _pr_view(root: Path, ctx: dict[str, Any], args: list[str]) -> tuple[dict[str, Any], int]:
    mocked = common.mock_fixture(root, f"pr-view-{common.fixture_name()}")
    if mocked:
        return mocked, 0
    project = ctx["project"]
    if not project:
        return common.fail_json("pr-view", PROVIDER, "missing-repo"), 30
    number = common.kv_get(args, "number")
    url_arg = common.kv_get(args, "url")
    if not number and url_arg:
        number = common.pr_number_from_url(url_arg, r"/merge_requests/(\d+)")
    if not number:
        return common.fail_json("pr-view", PROVIDER, "missing-pr-number"), 30
    url = f"{ctx['apiBase']}/projects/{project}/merge_requests/{number}"
    transport = common.http_request(root=root, provider=PROVIDER, method="GET", url=url, token_env=ctx["tokenEnv"])
    if "body" not in transport:
        return common.fail_json("pr-view", PROVIDER, "transport-failed"), 30
    return common.emit_verb_ok("pr-view", PROVIDER, gitlab_mr_to_view(json.loads(common.parse_transport_body(transport)))), 0


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
    body = common.kv_get(args, "body")
    head = common.kv_get(args, "head")
    base = common.kv_get(args, "base")
    if not title or not head or not base:
        return common.fail_json("pr-create", PROVIDER, "missing-fields"), 30
    mocked = common.mock_fixture(root, f"pr-create-{common.fixture_name()}")
    if mocked:
        return mocked, 0
    project = ctx["project"]
    if not project:
        return common.fail_json("pr-create", PROVIDER, "missing-repo"), 30
    payload = json.dumps({"title": title, "description": body, "source_branch": head, "target_branch": base})
    url = f"{ctx['apiBase']}/projects/{project}/merge_requests"
    transport = common.http_request(root=root, provider=PROVIDER, method="POST", url=url, token_env=ctx["tokenEnv"], body=payload.encode())
    if "body" not in transport:
        return common.fail_json("pr-create", PROVIDER, "transport-failed"), 30
    return common.emit_verb_ok("pr-create", PROVIDER, gitlab_mr_to_view(json.loads(common.parse_transport_body(transport)))), 0


def _pr_close(root: Path, ctx: dict[str, Any], args: list[str]) -> tuple[dict[str, Any], int]:
    number = common.kv_get(args, "number")
    if not number:
        return common.fail_json("pr-close", PROVIDER, "missing-pr-number"), 30
    mocked = common.mock_fixture(root, f"pr-close-{common.fixture_name()}")
    if mocked:
        return mocked, 0
    project = ctx["project"]
    url = f"{ctx['apiBase']}/projects/{project}/merge_requests/{number}"
    transport = common.http_request(root=root, provider=PROVIDER, method="PUT", url=url, token_env=ctx["tokenEnv"], body=b'{"state_event":"close"}')
    if "body" not in transport:
        return common.fail_json("pr-close", PROVIDER, "transport-failed"), 30
    return common.emit_verb_ok("pr-close", PROVIDER, gitlab_mr_to_view(json.loads(common.parse_transport_body(transport)))), 0


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
    project = ctx["project"]
    url = f"{ctx['apiBase']}/projects/{project}/repository/commits/{sha}/statuses?per_page=100"
    transport = common.http_request(root=root, provider=PROVIDER, method="GET", url=url, token_env=ctx["tokenEnv"])
    if "body" not in transport:
        url2 = f"{ctx['apiBase']}/projects/{project}/pipelines?sha={sha}&per_page=100"
        transport = common.http_request(root=root, provider=PROVIDER, method="GET", url=url2, token_env=ctx["tokenEnv"])
    if "body" not in transport:
        return common.fail_json("checks", PROVIDER, "transport-failed"), 30
    return common.emit_verb_ok("checks", PROVIDER, common.map_gitlab_checks(common.parse_transport_body(transport))), 0


def _review_threads(root: Path, ctx: dict[str, Any], args: list[str]) -> tuple[dict[str, Any], int]:
    number = common.kv_get(args, "number")
    if not number:
        return common.fail_json("review-threads", PROVIDER, "missing-pr-number"), 30
    mocked = common.mock_fixture(root, f"review-threads-{common.fixture_name()}")
    if mocked:
        return mocked, 0
    project = ctx["project"]
    url = f"{ctx['apiBase']}/projects/{project}/merge_requests/{number}/discussions?per_page=100"
    transport = common.http_request(root=root, provider=PROVIDER, method="GET", url=url, token_env=ctx["tokenEnv"])
    if "body" not in transport:
        return common.fail_json("review-threads", PROVIDER, "transport-failed"), 30
    discussions = json.loads(common.parse_transport_body(transport))
    if not isinstance(discussions, list):
        discussions = []
    unresolved = actionable = 0
    for discussion in discussions:
        for note in discussion.get("notes") or []:
            if note.get("resolvable") and not note.get("resolved"):
                unresolved += 1
                if not note.get("system"):
                    actionable += 1
    return common.emit_verb_ok("review-threads", PROVIDER, {"unresolved": unresolved, "actionable": actionable}), 0


def _merge(root: Path, ctx: dict[str, Any], args: list[str]) -> tuple[dict[str, Any], int]:
    number = common.kv_get(args, "number")
    if not number:
        return common.fail_json("merge", PROVIDER, "missing-pr-number"), 30
    mocked = common.mock_fixture(root, f"merge-{common.fixture_name()}")
    if mocked:
        return mocked, 0
    project = ctx["project"]
    url = f"{ctx['apiBase']}/projects/{project}/merge_requests/{number}/merge"
    body = b'{"merge_when_pipeline_succeeds":false,"should_remove_source_branch":false}'
    transport = common.http_request(root=root, provider=PROVIDER, method="PUT", url=url, token_env=ctx["tokenEnv"], body=body)
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
    project = ctx.get("project")
    if not project:
        return common.fail_json("remote-ref-exists", PROVIDER, "missing-repo"), 30
    from urllib.parse import quote
    encoded = quote(str(project), safe="")
    branch_enc = quote(branch, safe="")
    url = f"{ctx['apiBase']}/projects/{encoded}/repository/branches/{branch_enc}"
    transport = common.http_request(root=root, provider=PROVIDER, method="GET", url=url, token_env=ctx["tokenEnv"])
    return common.remote_ref_exists_from_transport(verb="remote-ref-exists", provider=PROVIDER, branch=branch, transport=transport)


