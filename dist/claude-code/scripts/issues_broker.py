"""Broker credential helpers for issue-store clients (PRD 080 phase 19 / R1, R3)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import urlparse

from credentials.model import Resolution, ResolutionState, ResolvedToken
from credentials.send_path import authorization_header, broker_send


class IssuesBrokerError(RuntimeError):
    """Fail-closed broker refusal for issue-store clients."""

    def __init__(self, message: str, *, code: str = "broker-error") -> None:
        self.code = code
        super().__init__(message)


def token_from_credential(credential: Resolution | ResolvedToken | None) -> tuple[str | None, str | None]:
    """Return (token, refusal_reason). Refusal precedes any header attachment."""
    if isinstance(credential, Resolution):
        if credential.state is ResolutionState.UNRESOLVED:
            return None, credential.reason or "credential-unresolved"
        if credential.state is ResolutionState.EXPLICITLY_NO_AUTH:
            return None, "explicitly-no-auth"
        if credential.token is None or not credential.token.token.value.strip():
            return None, "credential-unresolved"
        return credential.token.token.value, None
    if isinstance(credential, ResolvedToken):
        value = credential.token.value.strip()
        if not value:
            return None, "credential-unresolved"
        return value, None
    return None, "missing-credential"


def require_token(credential: Resolution | ResolvedToken | None) -> str:
    token, reason = token_from_credential(credential)
    if not token:
        raise IssuesBrokerError(reason or "missing-credential", code=reason or "missing-credential")
    return token


def principal_account(credential: Resolution | ResolvedToken | None) -> str | None:
    if isinstance(credential, Resolution) and credential.token and credential.token.principal:
        account = credential.token.principal.account
        return account.strip() if isinstance(account, str) and account.strip() else None
    if isinstance(credential, ResolvedToken) and credential.principal:
        account = credential.principal.account
        return account.strip() if isinstance(account, str) and account.strip() else None
    return None


def hosts_from_urls(*urls: str) -> set[str]:
    hosts: set[str] = set()
    for url in urls:
        if not isinstance(url, str) or not url.strip():
            continue
        hostname = (urlparse(url.strip()).hostname or "").strip().lower()
        if hostname:
            hosts.add(hostname)
    return hosts


def merge_allowed_hosts(*groups: Iterable[str] | None) -> set[str]:
    allowed: set[str] = set()
    for group in groups:
        if not group:
            continue
        for host in group:
            value = str(host).strip().lower()
            if value:
                allowed.add(value)
    return allowed


def prepare_bound_headers(
    *,
    url: str,
    allowed_hosts: Iterable[str],
    bearer_token: str | None = None,
    extra_headers: Mapping[str, str] | None = None,
    method: str = "GET",
) -> dict[str, str]:
    """Validate destination via broker_send, then return headers (auth only after allowlist)."""
    prepared = broker_send(
        api_base=url,
        allowed_hosts=allowed_hosts,
        bearer_token=bearer_token,
        method=method,
        extra_headers=extra_headers,
        transport=None,
    )
    if prepared.refused:
        raise IssuesBrokerError(
            prepared.reason or "endpoint not allowlisted",
            code="endpoint-refused",
        )
    headers = dict(prepared.headers)
    # Ensure Authorization is only present when the broker did not refuse.
    if authorization_header(prepared) is None:
        headers.pop("Authorization", None)
    return headers


def strip_auth_headers(headers: Mapping[str, str] | None) -> dict[str, str]:
    """Drop auth material so the broker can re-attach after endpoint binding."""
    if not headers:
        return {}
    out: dict[str, str] = {}
    for key, value in headers.items():
        lower = str(key).lower()
        if lower in {"authorization", "private-token"}:
            continue
        out[str(key)] = str(value)
    return out


def ssrf_allowlist_from_host_cfg(host_cfg: Mapping[str, Any] | None) -> set[str]:
    if not isinstance(host_cfg, Mapping):
        return set()
    raw = host_cfg.get("ssrfAllowlist")
    if not isinstance(raw, list):
        return set()
    return {str(item).strip().lower() for item in raw if str(item).strip()}
