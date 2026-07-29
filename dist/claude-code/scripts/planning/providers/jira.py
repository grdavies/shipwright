"""Jira issues provider adapter (PRD 082 phase 13 / R27)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import issues_http
import planning_visibility

PROVIDER_ID = "jira"
BROKER_ID = "jira"
MIN_SCOPES = ("read:jira-work", "write:jira-work")


def _ps():
    import planning_store as ps

    return ps


def native_links_capable_probe(token: str, cfg: dict[str, Any], root: Path) -> bool:
    from planning_jira_probe import _api_base, _auth_header, _http_get

    base = _api_base(cfg)
    headers = _auth_header(cfg, token)
    if not base or not headers:
        return False
    try:
        status, _payload = _http_get(f"{base}/issueLinkType", headers, root=root)
    except Exception:
        return False
    return status < 400


def attach_native_links_capable(
    probe: dict[str, Any],
    token: str,
    cfg: dict[str, Any],
    root: Path,
) -> None:
    if probe.get("verdict") != "ok":
        probe["nativeLinksCapable"] = False
        return
    probe["nativeLinksCapable"] = native_links_capable_probe(token, cfg, root)


def scope_probe(root: Path, cfg: dict[str, Any], token: str) -> dict[str, Any]:
    from planning_jira_probe import probe_jira_init

    return probe_jira_init(cfg, token, root)


def privacy_create_gate(root: Path, cfg: dict[str, Any], unit_id: str, body_path: str, content: str) -> None:
    """R105 — fail-closed on create when shared Jira project + private/memory unit."""
    issues = _ps().resolve_issues_provider(cfg)
    if issues.get("provider") != PROVIDER_ID:
        return
    from planning_jira_probe import probe_jira_privacy

    artifact_type = _ps().require_artifact_type(body_path, content=content)
    unit: dict[str, Any] = {"id": unit_id, "type": artifact_type, "bodyPath": body_path}
    explicit = _ps().parse_visibility_from_content(content)
    if explicit:
        unit["visibility"] = explicit
    resolved = planning_visibility.resolve_unit_visibility(unit, cfg)
    if not planning_visibility.body_is_redacted(resolved["visibility"]):
        return
    probe = probe_jira_privacy(cfg, root)
    if probe.get("verdict") != "ok":
        _ps().fail(
            probe.get("error", "per-issue-privacy-unsupported"),
            code="visibility-refused",
            visibility=resolved["visibility"],
            unitId=unit_id,
            remediation=probe.get("remediation"),
        )
    _ps().fail(
        "per-issue-privacy-unsupported-on-jira",
        code="visibility-refused",
        visibility=resolved["visibility"],
        unitId=unit_id,
        remediation="use separate Jira project per visibility tier or reroute per PRD 043 R28/R43",
    )


def store_project_browse_private(root: Path, cfg: dict[str, Any], project_key: str) -> bool | None:
    from planning_jira_probe import _api_base, _auth_header, resolve_jira_flavor

    token_env = _ps().resolve_issues_token_env(cfg, PROVIDER_ID)
    api_token = os.environ.get(token_env, "") if token_env else ""
    if not api_token:
        return None
    if resolve_jira_flavor(cfg) == "dc":
        headers = {"Authorization": f"Bearer {api_token}", "Accept": "application/json"}
    else:
        headers = _auth_header(cfg, api_token)
    base = _api_base(cfg)
    if not base or not headers:
        return None
    url = f"{base}/project/{project_key}/permissionscheme"
    request_headers = {**headers, "User-Agent": "shipwright-planning-store"}
    try:
        status, _resp_headers, body = issues_http.http_request(
            "GET",
            url,
            request_headers,
            root=root,
            issues_provider=PROVIDER_ID,
            timeout=15,
        )
        if status >= 400:
            return None
        data = json.loads(body)
    except (ConnectionError, json.JSONDecodeError, TimeoutError):
        return None
    if not isinstance(data, dict):
        return None
    browse_holders = [
        entry.get("holder")
        for entry in data.get("permissions") or []
        if isinstance(entry, dict) and entry.get("permission") == "BROWSE_PROJECTS"
    ]
    browse_holders = [h for h in browse_holders if isinstance(h, dict)]
    if not browse_holders:
        return None
    unrestricted_holder_types = {"anyone", "loggedin", "authenticated"}
    if any(str(h.get("type", "")).strip().lower() in unrestricted_holder_types for h in browse_holders):
        return False
    return True


def destination_endpoint(cfg: dict[str, Any]) -> str:
    from planning_jira_probe import resolve_jira_endpoint

    endpoint = resolve_jira_endpoint(cfg)
    return endpoint or ""


def wire_client(root: Path, credential: Any) -> Any:
    from planning_jira_client import JiraIssuesClient

    return JiraIssuesClient(root, credential=credential)
