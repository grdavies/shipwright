#!/usr/bin/env python3
"""CodeRabbit review adapter for the gate path (PRD 042 R9 — no GitHub CLI)."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from host_invoke import host_verb  # noqa: E402


def _env(name: str) -> str:
    return os.environ.get(name) or ""


def _parse_checks(path: str) -> str:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "absent"
    for row in data if isinstance(data, list) else []:
        name = str(row.get("name") or "")
        if re.search("coderabbit", name, re.I):
            return str(row.get("state") or "absent")
    return "absent"


def _graphql_reviews(root: Path, owner: str, repo: str, pr: str) -> str:
    query = (
        "query($o:String!,$r:String!,$p:Int!){repository(owner:$o,name:$r)"
        "{pullRequest(number:$p){reviews(last:50){nodes{author{login} submittedAt commit{oid}}}}}}"
    )
    payload = json.dumps({"query": query, "variables": {"o": owner, "r": repo, "p": int(pr)}})
    from _sw.host import _common as common  # noqa: E402
    from host_lib import github_api_base, host_section, load_workflow_config, resolve_token_env  # noqa: E402

    cfg = load_workflow_config(root)
    host = host_section(cfg)
    token_env = resolve_token_env(host, "github")
    url = f"{github_api_base(host)}/graphql"
    transport = common.http_request(root=root, provider="github", method="POST", url=url, token_env=token_env, body=payload.encode())
    body = common.parse_transport_body(transport)
    try:
        nodes = (((json.loads(body).get("data") or {}).get("repository") or {}).get("pullRequest") or {}).get("reviews", {}).get("nodes") or []
    except json.JSONDecodeError:
        return ""
    cr = [n for n in nodes if re.search("coderabbit", str((n.get("author") or {}).get("login") or ""), re.I)]
    if not cr:
        return ""
    cr.sort(key=lambda n: str(n.get("submittedAt") or ""))
    return str(((cr[-1].get("commit") or {}).get("oid")) or "")


def _issue_comments(root: Path, owner_repo: str, pr: str, out_path: Path) -> None:
    owner, repo = owner_repo.split("/", 1)
    from _sw.host import _common as common  # noqa: E402
    from host_lib import github_api_base, host_section, load_workflow_config, resolve_token_env  # noqa: E402

    cfg = load_workflow_config(root)
    host = host_section(cfg)
    token_env = resolve_token_env(host, "github")
    url = f"{github_api_base(host)}/repos/{owner}/{repo}/issues/{pr}/comments?per_page=100"
    transport = common.http_request(root=root, provider="github", method="GET", url=url, token_env=token_env)
    body = common.parse_transport_body(transport)
    try:
        items = json.loads(body)
        if not isinstance(items, list):
            items = []
    except json.JSONDecodeError:
        items = []
    out_path.write_text(json.dumps(items), encoding="utf-8")


def _commit_minutes(root: Path, owner_repo: str, sha: str) -> int:
    owner, repo = owner_repo.split("/", 1)
    from _sw.host import _common as common  # noqa: E402
    from host_lib import github_api_base, host_section, load_workflow_config, resolve_token_env  # noqa: E402

    cfg = load_workflow_config(root)
    host = host_section(cfg)
    token_env = resolve_token_env(host, "github")
    url = f"{github_api_base(host)}/repos/{owner}/{repo}/commits/{sha}"
    transport = common.http_request(root=root, provider="github", method="GET", url=url, token_env=token_env)
    body = common.parse_transport_body(transport)
    try:
        date_s = ((json.loads(body).get("commit") or {}).get("committer") or {}).get("date") or ""
        if not date_s:
            return 0
        dt = datetime.fromisoformat(date_s.replace("Z", "+00:00"))
        now = int(os.environ.get("SW_GATE_NOW") or time.time())
        return max(0, (now - int(dt.timestamp())) // 60)
    except (json.JSONDecodeError, ValueError, TypeError):
        return 0


def main() -> int:
    pr = _env("SW_PR")
    head_sha = _env("SW_HEAD_SHA")
    owner_repo = _env("SW_OWNER_REPO")
    checks_file = _env("SW_CHECKS_FILE")
    issue_comments_file = _env("SW_ISSUE_COMMENTS_FILE")
    grace_min = int(_env("SW_GRACE_MIN") or "15")
    root = Path(_env("SW_ROOT") or Path.cwd())

    owner = _env("SW_OWNER") or (owner_repo.split("/")[0] if owner_repo else "")
    repo = _env("SW_REPO") or (owner_repo.split("/")[1] if "/" in owner_repo else "")

    cr_status = _parse_checks(checks_file)
    cr_reviewed_head = ""
    if owner and repo and pr:
        try:
            cr_reviewed_head = _graphql_reviews(root, owner, repo, pr)
        except Exception:
            cr_reviewed_head = ""

    out_path = Path(issue_comments_file)
    if owner_repo and pr:
        _issue_comments(root, owner_repo, pr, out_path)
    elif not out_path.is_file():
        out_path.write_text("[]", encoding="utf-8")

    try:
        comments = json.loads(out_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        comments = []

    cr_body = ""
    for row in reversed(comments if isinstance(comments, list) else []):
        login = str((row.get("user") or {}).get("login") or "")
        body = str(row.get("body") or "")
        if re.search("coderabbit", login, re.I) and re.search("summarize by coderabbit", body, re.I):
            cr_body = body
            break
    if not cr_body:
        for row in reversed(comments if isinstance(comments, list) else []):
            login = str((row.get("user") or {}).get("login") or "")
            if re.search("coderabbit", login, re.I):
                cr_body = str(row.get("body") or "")
                break

    cr_marker = int(bool(re.search(r"currently processing new changes|review in progress by coderabbit", cr_body, re.I)))
    cr_skip = int(bool(re.search(r"skip review by coderabbit|no new commits to review since the last review", cr_body, re.I)))
    cr_done = int(bool(re.search(r"no actionable comments were generated|actionable comments posted:", cr_body, re.I)))

    cr_installed = bool(cr_reviewed_head or cr_status != "absent" or cr_marker or cr_skip or cr_done)
    mins_since = _commit_minutes(root, owner_repo, head_sha) if head_sha and owner_repo else 0

    if not cr_installed:
        if mins_since < grace_min:
            cr_state, cr_landed = "in-flight", False
        else:
            cr_state, cr_landed = "unconfigured", True
    elif cr_marker or cr_status in ("PENDING", "IN_PROGRESS"):
        cr_state, cr_landed = "in-flight", False
    elif cr_status == "SUCCESS" or cr_reviewed_head == head_sha:
        cr_state = "skipped" if cr_skip else "landed"
        cr_landed = True
    elif (cr_skip or cr_done) and mins_since >= grace_min:
        cr_state = "skipped" if cr_skip else "landed"
        cr_landed = True
    else:
        cr_state, cr_landed = "in-flight", False

    payload = {
        "capabilities": {"perHeadState": True},
        "perHeadState": cr_state,
        "perHeadLanded": cr_landed,
        "reviewedHead": cr_reviewed_head or None,
        "statusContext": cr_status,
        "inProgressMarker": bool(cr_marker),
        "skipped": bool(cr_skip),
        "minutesSinceHeadPush": mins_since,
    }
    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
