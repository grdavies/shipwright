#!/usr/bin/env python3
"""Jira init probes for PRD 047 phase 2 (R101/R105/R108/R109)."""
from __future__ import annotations
import base64, json, os
from pathlib import Path
from typing import Any
import issues_http
JIRA_CLOUD_API = "/rest/api/3"
JIRA_DC_API = "/rest/api/2"
MIN_JIRA_SCOPES = ["read:jira-work", "write:jira-work"]
LABEL_DEGRADATION_LADDER = ("labels", "components", "customField")
CLIENT_SATISFIED_CREATE_FIELDS = frozenset({"summary", "project", "reporter", "issuetype", "description"})

def use_fixture_mode() -> bool:
    return os.environ.get("SW_ISSUES_FIXTURE", "").strip().lower() in {"1", "true", "yes"}

def resolve_jira_flavor(cfg):
    from planning_store import issues_section
    flavor = issues_section(cfg).get("flavor")
    return "dc" if isinstance(flavor, str) and flavor.strip().lower() == "dc" else "cloud"

def resolve_jira_endpoint(cfg):
    from planning_store import issues_section
    endpoint = issues_section(cfg).get("endpoint")
    return endpoint.rstrip("/") if isinstance(endpoint, str) and endpoint.strip() else ""

def resolve_jira_email_env(cfg):
    from planning_store import issues_section
    email_env = issues_section(cfg).get("emailEnv")
    return email_env.strip() if isinstance(email_env, str) and email_env.strip() else "ISSUES_JIRA_EMAIL"

def resolve_jira_project_key(cfg):
    from planning_store import store_section
    raw = store_section(cfg).get("projectKey")
    return raw.strip() if isinstance(raw, str) else ""

def resolve_jira_api_project_key(cfg, token: str | None = None, root: Path | None = None):
    """Canonical Jira project key for REST writes (createmeta may differ in case from config)."""
    config_key = resolve_jira_project_key(cfg)
    if not config_key:
        return ""
    if use_fixture_mode():
        return config_key.upper()
    from planning_store import issues_section

    issues = issues_section(cfg)
    raw_env = issues.get("tokenEnv")
    token_env = raw_env.strip() if isinstance(raw_env, str) and raw_env.strip() else "ISSUES_JIRA_TOKEN"
    auth_token = (token or os.environ.get(token_env, "")).strip()
    if not auth_token:
        return config_key
    headers = _auth_header(cfg, auth_token)
    base = _api_base(cfg)
    if not base or not headers:
        return config_key
    status, payload = _http_get(
        f"{base}/issue/createmeta?projectKeys={config_key}",
        headers,
        root=root,
    )
    if status >= 400 or not isinstance(payload, dict):
        return config_key
    for project in payload.get("projects") or []:
        if not isinstance(project, dict):
            continue
        api_key = project.get("key")
        if isinstance(api_key, str) and api_key.strip():
            return api_key.strip()
    return config_key

def resolve_jira_issue_type(cfg):
    from planning_store import issues_section
    issue_type = issues_section(cfg).get("issueType")
    return issue_type.strip() if isinstance(issue_type, str) and issue_type.strip() else "Task"

def resolve_label_surface(cfg):
    from planning_store import issues_section
    issues = issues_section(cfg)
    surface = issues.get("labelSurface")
    if isinstance(surface, str) and surface.strip().lower() in LABEL_DEGRADATION_LADDER:
        return surface.strip().lower()
    custom = issues.get("labelCustomField")
    return "customField" if isinstance(custom, str) and custom.strip() else "labels"

def resolve_field_defaults(cfg):
    from planning_store import issues_section
    raw = issues_section(cfg).get("fieldDefaults")
    return {str(k): str(v) for k, v in raw.items() if isinstance(raw, dict) and isinstance(k, str) and isinstance(v, str)} if isinstance(raw, dict) else {}

def _api_base(cfg):
    endpoint = resolve_jira_endpoint(cfg)
    suffix = JIRA_DC_API if resolve_jira_flavor(cfg) == "dc" else JIRA_CLOUD_API
    return f"{endpoint}{suffix}" if endpoint else ""

def _auth_header(cfg, token):
    if resolve_jira_flavor(cfg) == "dc":
        return {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    email = os.environ.get(resolve_jira_email_env(cfg), "").strip()
    if not email:
        return {}
    cred = base64.b64encode(f"{email}:{token}".encode()).decode()
    return {"Authorization": f"Basic {cred}", "Accept": "application/json"}

def _http_get(url, headers, timeout=15, root: Path | None = None):
    root = root or Path.cwd()
    hdrs = {**headers, "User-Agent": "shipwright-jira-probe"}
    status, _hdrs, body = issues_http.http_request(
        "GET",
        url,
        hdrs,
        root=root,
        issues_provider="jira",
        timeout=timeout,
    )
    try:
        payload = json.loads(body) if body.strip() else {}
    except json.JSONDecodeError:
        payload = {"message": body[:200]}
    return status, payload if isinstance(payload, dict) else {"message": str(payload)}

def probe_jira_auth(cfg, token, root: Path | None = None):
    flavor = resolve_jira_flavor(cfg)
    if use_fixture_mode():
        if flavor == "dc" and token.startswith("basic:"):
            return {"verdict": "fail", "error": "dc-password-rejected", "flavor": flavor, "message": "DC/Server requires PAT; password/basic auth rejected"}
        return {"verdict": "ok", "flavor": flavor, "fixture": True, "requiredScopes": MIN_JIRA_SCOPES}
    if flavor == "dc" and (token.startswith("basic:") or (":" in token and not token.startswith("pat:"))):
        return {"verdict": "fail", "error": "dc-password-rejected", "flavor": flavor, "message": "DC/Server requires PAT; password/basic auth rejected"}
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"} if flavor == "dc" else _auth_header(cfg, token)
    if flavor == "cloud" and not headers:
        email_env = resolve_jira_email_env(cfg)
        return {"verdict": "fail", "error": "missing-email", "flavor": flavor, "emailEnv": email_env, "message": f"Cloud auth requires email in {email_env}"}
    base = _api_base(cfg)
    if not base:
        return {"verdict": "fail", "error": "missing-endpoint", "flavor": flavor}
    status, _ = _http_get(f"{base}/myself", headers, root=root)
    if status >= 400:
        return {"verdict": "fail", "error": "auth-failed", "flavor": flavor, "httpStatus": status}
    return {"verdict": "ok", "flavor": flavor, "requiredScopes": MIN_JIRA_SCOPES}

def probe_jira_createmeta(cfg, token, root: Path | None = None):
    issue_type = resolve_jira_issue_type(cfg)
    defaults = resolve_field_defaults(cfg)
    if use_fixture_mode():
        fixture_path = os.environ.get("SW_JIRA_CREATEMETA_FIXTURE", "").strip()
        if fixture_path:
            data = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
            required = [f for f in data.get("requiredFields", []) if f not in defaults]
            if required:
                return {"verdict": "fail", "error": "required-fields-unmet", "requiredFields": required, "fieldDefaults": defaults, "remediation": "configure planning.store.issues.fieldDefaults or satisfy fields in Jira admin"}
        return {"verdict": "ok", "fixture": True, "issueType": issue_type}
    flavor = resolve_jira_flavor(cfg)
    headers = _auth_header(cfg, token) if flavor == "cloud" else {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    base = _api_base(cfg)
    project_key = resolve_jira_project_key(cfg)
    if not base or not project_key:
        return {"verdict": "fail", "error": "missing-config", "probe": "createmeta"}
    status, payload = _http_get(f"{base}/issue/createmeta?projectKeys={project_key}&expand=projects.issuetypes.fields", headers, root=root)
    if status >= 400:
        return {"verdict": "fail", "error": "createmeta-failed", "httpStatus": status}
    required_fields = []
    for project in (payload or {}).get("projects") or []:
        if not isinstance(project, dict):
            continue
        for itype in project.get("issuetypes") or []:
            if not isinstance(itype, dict) or str(itype.get("name", "")).lower() != issue_type.lower():
                continue
            for field_id, meta in (itype.get("fields") or {}).items():
                if (
                    isinstance(meta, dict)
                    and meta.get("required")
                    and field_id not in defaults
                    and field_id not in CLIENT_SATISFIED_CREATE_FIELDS
                ):
                    required_fields.append(str(field_id))
    if required_fields:
        return {"verdict": "fail", "error": "required-fields-unmet", "requiredFields": sorted(required_fields), "fieldDefaults": defaults, "remediation": "configure planning.store.issues.fieldDefaults or satisfy fields in Jira admin"}
    return {"verdict": "ok", "issueType": issue_type, "satisfiedDefaults": list(defaults.keys())}

def probe_jira_label_write(cfg, token, root: Path | None = None):
    surface = resolve_label_surface(cfg)
    if use_fixture_mode():
        denied = os.environ.get("SW_JIRA_LABEL_WRITE_DENIED", "").strip().lower() in {"1", "true", "yes"}
        if denied:
            next_surface = {"labels": "components", "components": "customField"}.get(surface)
            if not next_surface:
                return {"verdict": "fail", "error": "label-write-denied", "surface": surface, "message": "no writable label surface available"}
            return {"verdict": "ok", "fixture": True, "surface": next_surface, "degraded": True, "ladder": list(LABEL_DEGRADATION_LADDER)}
        return {"verdict": "ok", "fixture": True, "surface": surface, "ladder": list(LABEL_DEGRADATION_LADDER)}
    auth = probe_jira_auth(cfg, token, root=root)
    if auth.get("verdict") != "ok":
        return auth
    return {"verdict": "ok", "surface": surface, "ladder": list(LABEL_DEGRADATION_LADDER), "bodyMarkerAuthoritative": True}

def probe_jira_privacy(cfg, root):
    from planning_store import store_section
    import planning_visibility
    store = store_section(cfg)
    planning = cfg.get("planning") if isinstance(cfg.get("planning"), dict) else {}
    profile = str(planning.get("visibilityProfile") or "specs-public")
    project_visibility = store.get("jiraProjectVisibility")
    shared = project_visibility.strip().lower() in {"public", "shared"} if isinstance(project_visibility, str) else profile in {"specs-public", "all-public"}
    if use_fixture_mode():
        has_private = os.environ.get("SW_JIRA_PRIVATE_UNIT", "").strip().lower() in {"1", "true", "yes"}
        if shared and has_private:
            return {"verdict": "fail", "error": "per-issue-privacy-unsupported", "sharedProject": True, "remediation": "use separate Jira project per visibility tier or reroute per PRD 043 R28/R43"}
        return {"verdict": "ok", "fixture": True, "perIssuePrivacy": False, "sharedProject": shared}
    if not shared:
        return {"verdict": "ok", "perIssuePrivacy": False, "sharedProject": False}
    private_units = []
    units_dir = root / "docs" / "planning"
    if units_dir.is_dir():
        for unit_file in units_dir.rglob("*.md"):
            try:
                content = unit_file.read_text(encoding="utf-8")
            except OSError:
                continue
            unit = {"id": unit_file.parent.name, "type": "prd", "bodyPath": str(unit_file.relative_to(root))}
            resolved = planning_visibility.resolve_unit_visibility(unit, cfg)
            if planning_visibility.body_is_redacted(resolved["visibility"]):
                private_units.append(unit["id"])
    if private_units:
        return {"verdict": "fail", "error": "per-issue-privacy-unsupported", "sharedProject": True, "privateUnits": private_units, "remediation": "use separate Jira project per visibility tier or reroute per PRD 043 R28/R43"}
    return {"verdict": "ok", "perIssuePrivacy": False, "sharedProject": shared}

def probe_jira_init(cfg, token, root):
    for probe in (lambda: probe_jira_auth(cfg, token, root), lambda: probe_jira_privacy(cfg, root), lambda: probe_jira_createmeta(cfg, token, root), lambda: probe_jira_label_write(cfg, token, root)):
        result = probe()
        if result.get("verdict") != "ok":
            return result
    labels = probe_jira_label_write(cfg, token, root)
    return {"verdict": "ok", "flavor": resolve_jira_flavor(cfg), "requiredScopes": MIN_JIRA_SCOPES, "perIssuePrivacy": False, "labelSurface": labels.get("surface", "labels"), "labelLadder": labels.get("ladder", list(LABEL_DEGRADATION_LADDER)), "bodyMarkerAuthoritative": True}
