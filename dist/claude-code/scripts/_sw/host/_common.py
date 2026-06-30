"""Shared host adapter utilities — kv parsing, fixtures, HTTP via host_transport."""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any
from urllib.parse import quote

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from _sw import jsonio  # noqa: E402
from _sw.host_transport import urllib_request  # noqa: E402
from host_lib import (  # noqa: E402
    bitbucket_api_base,
    github_api_base,
    gitlab_api_base,
    host_section,
    load_workflow_config,
    parse_owner_repo,
    resolve_provider,
    resolve_token_env,
    url_encode_project,
)


def kv_get(args: list[str], key: str, default: str = "") -> str:
    """Parse ``--key value`` pairs from a flat argument list."""
    i = 0
    while i < len(args):
        if args[i] == f"--{key}" and i + 1 < len(args):
            return args[i + 1]
        i += 1
    return default


def fixture_name() -> str:
    return os.environ.get("SW_HOST_FIXTURE", "")


def local_fixture_name() -> str:
    return os.environ.get("SW_LOCAL_GATE_FIXTURE") or os.environ.get("SW_HOST_FIXTURE", "")


def fixture_dir(root: Path) -> Path:
    return root / "scripts" / "test" / "fixtures" / "host"


def mock_fixture(root: Path, name: str) -> dict[str, Any] | None:
    """Load a canned verb response when SW_HOST_FIXTURE is set."""
    fix = fixture_name()
    if not fix:
        return None
    fdir = fixture_dir(root)
    candidates = [fdir / f"{name}.json"]
    if name.startswith("repo-meta-"):
        candidates.append(fdir / f"repo-meta-{fix}.json")
        candidates.append(fdir / "repo-meta-green.json")
    elif name.startswith("pr-view-"):
        candidates.append(fdir / f"pr-view-{fix}.json")
        candidates.append(fdir / "pr-view-green.json")
    elif name.startswith("pr-list-"):
        candidates.append(fdir / f"pr-list-{fix}.json")
        candidates.append(fdir / "pr-list-green.json")
    elif name.startswith("pr-create-"):
        candidates.append(fdir / f"pr-create-{fix}.json")
        candidates.append(fdir / "pr-create-green.json")
    elif name.startswith("pr-close-"):
        candidates.append(fdir / f"pr-close-{fix}.json")
        candidates.append(fdir / "pr-close-green.json")
    elif name.startswith("checks-"):
        candidates.append(fdir / "checks-green.json")
    elif name.startswith("review-threads-"):
        candidates.append(fdir / f"review-threads-{fix}.json")
        if "blocked" in fix:
            candidates.append(fdir / "review-threads-blocked-threads.json")
    elif name.startswith("merge-"):
        candidates.append(fdir / f"merge-{fix}.json")
    for path in candidates:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    return None


def mock_transport(root: Path, url: str) -> dict[str, Any] | None:
    """Return a transport payload from fixture URL mapping."""
    fix = fixture_name()
    if not fix:
        return None
    map_file = fixture_dir(root) / f"transport-{fix}.json"
    if not map_file.is_file():
        return None
    mapping = json.loads(map_file.read_text(encoding="utf-8"))
    for pattern, body in mapping.items():
        if pattern in url or url.endswith(pattern):
            body_text = body if isinstance(body, str) else json.dumps(body)
            return {"verdict": "ok", "status": 200, "body": body_text}
    return None


def http_request(
    *,
    root: Path,
    provider: str,
    method: str,
    url: str,
    token_env: str,
    body: bytes | None = None,
) -> dict[str, Any]:
    """Perform HTTP via urllib transport or fixture mock."""
    mocked = mock_transport(root, url)
    if mocked is not None:
        return mocked
    buf = io.StringIO()
    with redirect_stdout(buf):
        payload = urllib_request(
            method=method,
            url=url,
            root=root,
            provider=provider,
            token_env=token_env,
            body=body,
        )
    return payload


def parse_transport_body(transport: dict[str, Any]) -> str:
    body = transport.get("body") or ""
    if isinstance(body, str):
        return body
    return json.dumps(body)


def transport_ok(transport: dict[str, Any]) -> bool:
    verdict = transport.get("verdict")
    return verdict in ("ok", "degraded") and transport.get("status", 200) < 400 or (
        verdict == "ok" and "body" in transport
    )


def emit(payload: dict[str, Any]) -> None:
    jsonio.emit(payload, indent=2)


def emit_verb_ok(verb: str, provider: str, data: Any) -> dict[str, Any]:
    return {"verdict": "ok", "verb": verb, "provider": provider, "data": data}


def fail_json(verb: str, provider: str, reason: str, message: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {"verdict": "fail", "verb": verb, "provider": provider, "reason": reason}
    if message:
        out["message"] = message
    return out


def degraded_json(verb: str, provider: str, reason: str) -> dict[str, Any]:
    return {
        "verdict": "degraded",
        "verb": verb,
        "provider": provider,
        "reason": reason,
        "retryable": False,
    }


def git_branch(root: Path, default: str = "") -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return default
    return proc.stdout.strip() or default


def pr_number_from_url(url: str, pattern: str) -> str:
    match = re.search(pattern, url)
    return match.group(1) if match else ""


def github_context(root: Path) -> dict[str, Any]:
    resolved = resolve_provider(root)
    cfg = load_workflow_config(root)
    host = host_section(cfg)
    remote_url = resolved.get("remoteUrl")
    slug = parse_owner_repo(remote_url if isinstance(remote_url, str) else None)
    owner, repo = slug if slug else ("", "")
    return {
        "provider": resolved.get("provider", "github"),
        "tokenEnv": resolve_token_env(host, "github"),
        "apiBase": github_api_base(host),
        "owner": owner,
        "repo": repo,
        "nameWithOwner": f"{owner}/{repo}" if owner and repo else "",
        "degraded": resolved.get("degraded", False),
        "degradedReason": resolved.get("degradedReason"),
        "resolved": resolved,
    }


def gitlab_context(root: Path) -> dict[str, Any]:
    resolved = resolve_provider(root)
    cfg = load_workflow_config(root)
    host = host_section(cfg)
    remote_url = resolved.get("remoteUrl")
    slug = parse_owner_repo(remote_url if isinstance(remote_url, str) else None)
    owner, repo = slug if slug else ("", "")
    project = url_encode_project(owner, repo) if owner and repo else ""
    return {
        "provider": "gitlab",
        "tokenEnv": resolve_token_env(host, "gitlab"),
        "apiBase": gitlab_api_base(host),
        "owner": owner,
        "repo": repo,
        "project": project,
        "nameWithOwner": f"{owner}/{repo}" if owner and repo else "",
        "degraded": resolved.get("degraded", False),
        "degradedReason": resolved.get("degradedReason"),
        "resolved": resolved,
    }


def bitbucket_context(root: Path) -> dict[str, Any]:
    resolved = resolve_provider(root)
    cfg = load_workflow_config(root)
    host = host_section(cfg)
    remote_url = resolved.get("remoteUrl")
    slug = parse_owner_repo(remote_url if isinstance(remote_url, str) else None)
    owner, repo = slug if slug else ("", "")
    return {
        "provider": "bitbucket",
        "tokenEnv": resolve_token_env(host, "bitbucket"),
        "apiBase": bitbucket_api_base(host),
        "owner": owner,
        "repo": repo,
        "repoPath": f"repositories/{owner}/{repo}" if owner and repo else "",
        "nameWithOwner": f"{owner}/{repo}" if owner and repo else "",
        "degraded": resolved.get("degraded", False),
        "degradedReason": resolved.get("degradedReason"),
        "resolved": resolved,
    }


def map_github_checks(body_text: str) -> list[dict[str, Any]]:
    data = json.loads(body_text)
    runs = data.get("check_runs") or []
    by_name: dict[str, dict[str, Any]] = {}
    for run in runs:
        status = str(run.get("status") or "").upper()
        conclusion = str(run.get("conclusion") or "").upper()
        if status in ("QUEUED", "IN_PROGRESS", "PENDING"):
            state = "IN_PROGRESS"
        elif conclusion == "SUCCESS" or (status == "COMPLETED" and conclusion in ("SUCCESS", "NEUTRAL", "SKIPPED")):
            state = "SUCCESS" if conclusion != "NEUTRAL" else "NEUTRAL"
        elif conclusion in ("FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED"):
            state = "FAILURE"
        else:
            state = conclusion or status or "PENDING"
        entry = {
            "name": run.get("name") or "check",
            "state": state,
            "bucket": "pass"
            if state in ("SUCCESS", "SKIPPED", "NEUTRAL")
            else ("fail" if state == "FAILURE" else "pending"),
            "link": run.get("html_url") or "",
            "workflow": (run.get("app") or {}).get("slug") or "",
            "_started": run.get("started_at") or "",
        }
        name = entry["name"]
        prev = by_name.get(name)
        if prev is None or (entry["_started"], entry["link"]) >= (prev.get("_started", ""), prev.get("link", "")):
            by_name[name] = entry
    out: list[dict[str, Any]] = []
    for entry in by_name.values():
        entry.pop("_started", None)
        out.append(entry)
    return out


def map_gitlab_checks(body_text: str) -> list[dict[str, Any]]:
    data = json.loads(body_text)
    items = data if isinstance(data, list) else (data.get("values") or data.get("pipelines") or [])
    out: list[dict[str, Any]] = []
    for row in items:
        status = str(row.get("status") or row.get("state") or "").lower()
        if status in ("running", "pending", "in_progress", "created"):
            state = "IN_PROGRESS"
        elif status in ("success", "successful"):
            state = "SUCCESS"
        elif status in ("failed", "failure", "canceled", "cancelled"):
            state = "FAILURE"
        else:
            state = status.upper() or "PENDING"
        out.append(
            {
                "name": row.get("name") or row.get("ref") or "check",
                "state": state,
                "bucket": "pass"
                if state in ("SUCCESS", "SKIPPED", "NEUTRAL")
                else ("fail" if state == "FAILURE" else "pending"),
                "link": row.get("target_url") or row.get("web_url") or "",
                "workflow": "",
            }
        )
    return out


def map_bitbucket_checks(body_text: str) -> list[dict[str, Any]]:
    data = json.loads(body_text)
    items = data.get("values") if isinstance(data, dict) else data
    if not isinstance(items, list):
        items = []
    out: list[dict[str, Any]] = []
    for row in items:
        state_raw = str(row.get("state") or "").upper()
        if state_raw in ("INPROGRESS", "PENDING"):
            norm = "IN_PROGRESS"
        elif state_raw == "SUCCESSFUL":
            norm = "SUCCESS"
        elif state_raw == "FAILED":
            norm = "FAILURE"
        else:
            norm = state_raw or "PENDING"
        out.append(
            {
                "name": row.get("name") or row.get("key") or "check",
                "state": norm,
                "bucket": "pass"
                if norm in ("SUCCESS", "SKIPPED", "NEUTRAL")
                else ("fail" if norm == "FAILURE" else "pending"),
                "link": row.get("url") or "",
                "workflow": "",
            }
        )
    return out


def gl_state_filter(state: str) -> str:
    mapping = {"open": "opened", "opened": "opened", "closed": "closed", "merged": "merged", "all": "all"}
    return mapping.get(state.lower(), "opened")


def bb_state_filter(state: str) -> str:
    mapping = {"open": "OPEN", "closed": "DECLINED", "merged": "MERGED", "all": ""}
    return mapping.get(state.lower(), "OPEN")


def write_temp_json(obj: Any) -> Path:
    tmp = Path(tempfile.mkstemp(prefix="sw-host-", suffix=".json")[1])
    tmp.write_text(json.dumps(obj), encoding="utf-8")
    return tmp


def quote_bitbucket_q(q: str) -> str:
    return quote(q, safe="")
