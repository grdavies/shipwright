"""GitHub issues provider adapter (PRD 082 phase 13 / R27)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import issues_http
from host_lib import github_api_base, host_section

from ._common import probe_rate_limited_result

PROVIDER_ID = "github-issues"
BROKER_ID = "github"
MIN_SCOPES = ("repo",)


def _ps():
    import planning_store as ps

    return ps


def probe_headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "shipwright-planning-store",
    }


def fine_grained_probe(
    token: str,
    cfg: dict[str, Any],
    root: Path,
    *,
    required: set[str],
) -> dict[str, Any]:
    location = _ps().resolve_store_location(root, cfg)
    if location.get("verdict") != "ok":
        return {
            "verdict": "fail",
            "error": "store-location-unresolved",
            "message": str(location.get("error") or "unable to resolve store location for probe"),
        }
    owner = location.get("owner")
    repo = location.get("repo")
    if not isinstance(owner, str) or not owner.strip() or not isinstance(repo, str) or not repo.strip():
        return {
            "verdict": "fail",
            "error": "store-location-unresolved",
            "message": "store location missing owner/repo for fine-grained probe",
        }
    owner = owner.strip()
    repo = repo.strip()
    api_base = github_api_base(host_section(cfg))
    headers = probe_headers(token)
    probes = (
        (f"{api_base}/repos/{owner}/{repo}", "metadata"),
        (f"{api_base}/repos/{owner}/{repo}/issues?state=all&per_page=1", "issues"),
    )
    for probe_url, probe_kind in probes:
        try:
            status, _, _body = issues_http.http_request(
                "GET",
                probe_url,
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
                limited["probe"] = probe_kind
                return limited
            raise
        if status >= 400:
            if status in {401, 403}:
                return {
                    "verdict": "fail",
                    "error": "insufficient-scope",
                    "probe": probe_kind,
                    "httpStatus": status,
                    "scopes": [],
                    "required": sorted(required),
                    "message": f"GitHub fine-grained token lacks {probe_kind} access to {owner}/{repo}",
                }
            if status == 404:
                return {
                    "verdict": "fail",
                    "error": "repo-not-found",
                    "httpStatus": 404,
                    "owner": owner,
                    "repo": repo,
                    "message": f"Repository {owner}/{repo} not found or not accessible with this token",
                }
            return {"verdict": "fail", "error": "auth-failed", "httpStatus": status}
    return {
        "verdict": "ok",
        "scopes": [],
        "required": sorted(required),
        "tokenKind": "fine-grained",
        "probeRepo": f"{owner}/{repo}",
        "owner": owner,
        "repo": repo,
    }


def native_links_capable_probe(
    token: str,
    cfg: dict[str, Any],
    root: Path,
    *,
    owner: str,
    repo: str,
) -> bool:
    api_base = github_api_base(host_section(cfg))
    headers = probe_headers(token)
    headers["X-GitHub-Api-Version"] = "2026-03-10"
    url = f"{api_base}/repos/{owner}/{repo}/issues/1/sub_issues"
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
            repo=repo.strip(),
        )
    else:
        probe["nativeLinksCapable"] = False


def scope_probe(token: str, cfg: dict[str, Any], root: Path) -> dict[str, Any]:
    host = host_section(cfg)
    url = f"{github_api_base(host)}/user"
    headers = probe_headers(token)
    try:
        status, resp_headers, _body = issues_http.http_request(
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
    scopes_header = resp_headers.get("x-oauth-scopes") or resp_headers.get("X-OAuth-Scopes") or ""
    scopes = {s.strip() for s in scopes_header.split(",") if s.strip()}
    required = set(MIN_SCOPES)
    if scopes & required:
        return {
            "verdict": "ok",
            "scopes": sorted(scopes),
            "required": sorted(required),
            "tokenKind": "classic",
        }
    if "repo" in scopes or "public_repo" in scopes:
        return {
            "verdict": "ok",
            "scopes": sorted(scopes),
            "required": sorted(required),
            "tokenKind": "classic",
        }
    if not scopes:
        return fine_grained_probe(token, cfg, root, required=required)
    return {
        "verdict": "fail",
        "error": "insufficient-scope",
        "scopes": sorted(scopes),
        "required": sorted(required),
        "message": "GitHub token lacks repo/public_repo scope for issue-store",
    }


def store_repo_private(root: Path, cfg: dict[str, Any], owner: str, repo: str) -> bool | None:
    from issues_lib import IssueRateLimited

    token_env = _ps().resolve_issues_token_env(cfg, PROVIDER_ID)
    api_token = os.environ.get(token_env, "") if token_env else ""
    host = host_section(cfg)
    url = f"{github_api_base(host)}/repos/{owner}/{repo}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "shipwright-planning-store",
    }
    if api_token:
        headers["Authorization"] = f"Bearer {api_token}"
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
    if isinstance(data, dict) and "private" in data:
        return bool(data["private"])
    return None


def destination_endpoint(cfg: dict[str, Any]) -> str:
    return github_api_base(host_section(cfg))


def wire_client(root: Path, credential: Any) -> Any:
    from planning_github_client import GitHubIssuesClient

    return GitHubIssuesClient(root, credential=credential)
