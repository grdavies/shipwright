"""Planning issue provider adapters (PRD 082 phase 13 / R27)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from host_lib import token_present

from . import github, gitlab, jira, linear, notion
from ._boundary import provider_import_violations

PROVIDER_MODULES = {
    github.PROVIDER_ID: github,
    gitlab.PROVIDER_ID: gitlab,
    jira.PROVIDER_ID: jira,
    linear.PROVIDER_ID: linear,
    notion.PROVIDER_ID: notion,
}

MIN_ISSUES_SCOPES: dict[str, list[str]] = {
    github.PROVIDER_ID: list(github.MIN_SCOPES),
    gitlab.PROVIDER_ID: list(gitlab.MIN_SCOPES),
    jira.PROVIDER_ID: list(jira.MIN_SCOPES),
    linear.PROVIDER_ID: list(linear.MIN_SCOPES),
    notion.PROVIDER_ID: list(notion.MIN_SCOPES),
}

__all__ = [
    "MIN_ISSUES_SCOPES",
    "PROVIDER_MODULES",
    "attach_native_links_capable",
    "destination_endpoint",
    "github",
    "gitlab",
    "jira",
    "linear",
    "notion",
    "live_client_wired",
    "probe_issues_token",
    "provider_import_violations",
    "scope_probe",
    "store_host_privacy_for_provider",
    "wire_client",
]


def live_client_wired() -> bool:
    return linear.live_client_wired()


def destination_endpoint(cfg: dict[str, Any], issues_provider: str) -> str:
    module = PROVIDER_MODULES.get(issues_provider)
    if module is None or not hasattr(module, "destination_endpoint"):
        return ""
    return module.destination_endpoint(cfg)


def scope_probe(provider: str, token: str, cfg: dict[str, Any], root: Path) -> dict[str, Any]:
    module = PROVIDER_MODULES[provider]
    if provider == jira.PROVIDER_ID:
        return module.scope_probe(root, cfg, token)
    return module.scope_probe(token, cfg, root)


def attach_native_links_capable(
    provider: str,
    probe: dict[str, Any],
    token: str,
    cfg: dict[str, Any],
    root: Path,
) -> None:
    module = PROVIDER_MODULES.get(provider)
    if module is None or not hasattr(module, "attach_native_links_capable"):
        probe["nativeLinksCapable"] = False
        return
    module.attach_native_links_capable(probe, token, cfg, root)


def wire_client(provider: str, root: Path, credential: Any) -> Any:
    return PROVIDER_MODULES[provider].wire_client(root, credential)


def store_host_privacy_for_provider(
    provider: str,
    root: Path,
    cfg: dict[str, Any],
    *,
    owner: str = "",
    repo: str = "",
    project_key: str = "",
) -> bool | None:
    if provider == github.PROVIDER_ID and owner and repo:
        return github.store_repo_private(root, cfg, owner, repo)
    if provider == gitlab.PROVIDER_ID and owner and repo:
        return gitlab.store_project_private(root, cfg, owner, repo)
    if provider == jira.PROVIDER_ID and project_key:
        return jira.store_project_browse_private(root, cfg, project_key)
    return None


def probe_issues_token(root: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    import planning_store as ps

    issues = ps.resolve_issues_provider(cfg)
    provider = issues.get("provider", "none")
    if provider in {"none", ""} or not issues.get("supported"):
        return {
            "verdict": "ok",
            "skipped": True,
            "reason": "issues-provider-none-or-unsupported",
            "provider": provider,
        }
    if provider not in ps.SHIPPED_ISSUES_PROVIDERS:
        return {
            "verdict": "ok",
            "skipped": True,
            "reason": "issues-provider-not-shipped",
            "provider": provider,
        }
    token_env = ps.resolve_issues_token_env(cfg, provider)
    if not token_env:
        return {"verdict": "fail", "error": "missing-token-env", "provider": provider}
    if not token_present(token_env):
        return {
            "verdict": "fail",
            "error": "missing-token",
            "provider": provider,
            "tokenEnv": token_env,
            "message": f"Set {token_env} for issue-store API access (value never logged).",
        }
    if provider not in PROVIDER_MODULES:
        return {
            "verdict": "fail",
            "error": "probe-not-implemented",
            "provider": provider,
            "requiredScopes": MIN_ISSUES_SCOPES.get(provider, []),
        }
    token = os.environ.get(token_env, "")
    probe = scope_probe(provider, token, cfg, root)
    out: dict[str, Any] = {
        "verdict": probe.get("verdict", "fail"),
        "provider": provider,
        "tokenEnv": token_env,
        "tokenPresent": True,
        "requiredScopes": MIN_ISSUES_SCOPES.get(provider, []),
    }
    for key in (
        "error",
        "message",
        "scopes",
        "required",
        "httpStatus",
        "tokenKind",
        "probeRepo",
        "probe",
        "owner",
        "repo",
    ):
        if key in probe:
            out[key] = probe[key]
    attach_native_links_capable(provider, out, token, cfg, root)
    return out
