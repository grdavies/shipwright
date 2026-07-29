"""GitLab issues provider adapter (PRD 082 phase 13 / R27)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote

import issues_http
from host_lib import gitlab_api_base, host_section

from ._common import probe_rate_limited_result

PROVIDER_ID = "gitlab-issues"
BROKER_ID = "gitlab"
MIN_SCOPES = ("api",)


def _ps():
    import planning_store as ps

    return ps


def native_links_capable_probe(
    token: str,
    cfg: dict[str, Any],
    root: Path,
    *,
    owner: str,
    project: str,
) -> bool:
    api_base = gitlab_api_base(host_section(cfg))
    encoded = quote(f"{owner}/{project}", safe="")
    url = f"{api_base}/projects/{encoded}/issues/1/links"
    headers = {"PRIVATE-TOKEN": token, "User-Agent": "shipwright-planning-store"}
    try:
        status, _, _body = issues_http.http_request(
            "GET",
            url,
            headers,
            root=root,
            issues_provider=PROVIDER_ID,
            timeout=15,
        )
    except Exception:
        return False
    if status == 403:
        return False
    return status < 400 or status == 404


def attach_native_links_capable(
    probe: dict[str, Any],
    token: str,
    cfg: dict[str, Any],
    root: Path,
) -> None:
    if probe.get("verdict") != "ok":
        probe["nativeLinksCapable"] = False
        return
    owner = probe.get("owner")
    repo = probe.get("repo")
    probe_repo = probe.get("probeRepo")
    if (not owner or not repo) and isinstance(probe_repo, str) and "/" in probe_repo:
        owner, repo = probe_repo.split("/", 1)
    if not isinstance(owner, str) or not isinstance(repo, str) or not owner or not repo:
        location = _ps().resolve_store_location(root, cfg)
        owner = location.get("owner") if isinstance(location.get("owner"), str) else ""
        repo = location.get("repo") if isinstance(location.get("repo"), str) else ""
    if owner and repo:
        probe["nativeLinksCapable"] = native_links_capable_probe(
            token,
            cfg,
            root,
            owner=owner.strip(),
            project=repo.strip(),
        )
    else:
        probe["nativeLinksCapable"] = False


def scope_probe(token: str, cfg: dict[str, Any], root: Path) -> dict[str, Any]:
    host = host_section(cfg)
    url = f"{gitlab_api_base(host)}/user"
    headers = {"PRIVATE-TOKEN": token, "User-Agent": "shipwright-planning-store"}
    try:
        status, _, _body = issues_http.http_request(
            "GET",
            url,
            headers,
            root=root,
            issues_provider=PROVIDER_ID,
            timeout=15,
        )
    except ConnectionError as exc:
        return {"verdict": "fail", "error": "network-unavailable", "message": str(exc)}
    except Exception as exc:
        limited = probe_rate_limited_result(exc)
        if limited is not None:
            return limited
        raise
    if status >= 400:
        return {"verdict": "fail", "error": "auth-failed", "httpStatus": status}
    return {"verdict": "ok", "required": list(MIN_SCOPES)}


def store_project_private(root: Path, cfg: dict[str, Any], owner: str, project: str) -> bool | None:
    from issues_lib import IssueRateLimited

    token_env = _ps().resolve_issues_token_env(cfg, PROVIDER_ID)
    api_token = os.environ.get(token_env, "") if token_env else ""
    host = host_section(cfg)
    encoded = quote(f"{owner}/{project}", safe="")
    url = f"{gitlab_api_base(host)}/projects/{encoded}"
    headers = {"PRIVATE-TOKEN": api_token, "User-Agent": "shipwright-planning-store"}
    if not api_token:
        return None
    try:
        status, _, body = issues_http.http_request(
            "GET",
            url,
            headers,
            root=root,
            issues_provider=PROVIDER_ID,
            timeout=15,
        )
        if status >= 400:
            return None
        data = json.loads(body)
    except (IssueRateLimited, ConnectionError, json.JSONDecodeError, TimeoutError):
        return None
    if isinstance(data, dict):
        visibility = str(data.get("visibility", "")).strip().lower()
        if visibility == "private":
            return True
        if visibility in {"public", "internal"}:
            return False
    return None


def destination_endpoint(cfg: dict[str, Any]) -> str:
    return gitlab_api_base(host_section(cfg))


def wire_client(root: Path, credential: Any) -> Any:
    from planning_gitlab_client import GitLabIssuesClient

    return GitLabIssuesClient(root, credential=credential)
