"""Shared REST fetch SSRF enforcement for memory provider adapters (PRD 071 R5)."""

from __future__ import annotations

import ipaddress
import json
import urllib.parse
import urllib.request
from typing import Any
from urllib.error import URLError

_METADATA_HOSTS = frozenset(
    {
        "metadata.google.internal",
        "metadata.goog",
    }
)
_DEFAULT_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class RestFetchPolicyError(ValueError):
    """Raised when a REST URL fails SSRF policy validation."""


def _parse_url(url: str) -> urllib.parse.ParseResult:
    if not url or not isinstance(url, str):
        raise RestFetchPolicyError("url must be a non-empty string")
    try:
        parsed = urllib.parse.urlparse(url.strip())
    except ValueError as exc:
        raise RestFetchPolicyError(f"invalid url: {url!r}") from exc
    if parsed.scheme not in ("http", "https"):
        raise RestFetchPolicyError(f"unsupported scheme: {parsed.scheme!r}")
    if parsed.username or parsed.password:
        raise RestFetchPolicyError("embedded credentials are not allowed in REST base URLs")
    host = parsed.hostname
    if not host:
        raise RestFetchPolicyError("url missing hostname")
    return parsed


def _host_flags(host: str) -> tuple[bool, bool, bool, bool]:
    lowered = host.lower()
    if lowered in _METADATA_HOSTS:
        return False, False, False, True
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False, False, False, False
    return (
        bool(addr.is_loopback),
        bool(addr.is_private),
        bool(addr.is_link_local),
        addr == ipaddress.ip_address("169.254.169.254"),
    )


def default_rest_fetch_policy(*, agent_session: str = "") -> dict[str, Any]:
    """Fail-closed REST policy unless catalog transport metadata opts in."""
    session = str(agent_session or "").strip().lower()
    if session == "rest":
        return {
            "allowedHosts": [],
            "allowLoopback": False,
            "allowPrivate": False,
            "allowLinkLocal": False,
            "allowMetadata": False,
        }
    return {
        "allowedHosts": list(_DEFAULT_LOOPBACK_HOSTS),
        "allowLoopback": True,
        "allowPrivate": False,
        "allowLinkLocal": False,
        "allowMetadata": False,
    }


def rest_fetch_policy_from_transport(hook_transport: dict[str, Any] | None) -> dict[str, Any]:
    """Derive REST fetch policy from catalog hookTransport (not advisory-only)."""
    transport = hook_transport if isinstance(hook_transport, dict) else {}
    agent_session = str(transport.get("agentSession") or "").strip().lower()
    policy = default_rest_fetch_policy(agent_session=agent_session)
    raw = transport.get("restFetchPolicy")
    if not isinstance(raw, dict):
        return policy
    allowed = raw.get("allowedHosts")
    if isinstance(allowed, list):
        policy["allowedHosts"] = [str(host).strip().lower() for host in allowed if str(host).strip()]
    for key in ("allowLoopback", "allowPrivate", "allowLinkLocal", "allowMetadata"):
        if key in raw:
            policy[key] = bool(raw[key])
    return policy


def rest_fetch_policy_from_catalog_entry(entry: dict[str, Any]) -> dict[str, Any]:
    transport = entry.get("hookTransport")
    if not isinstance(transport, dict):
        return default_rest_fetch_policy()
    return rest_fetch_policy_from_transport(transport)


def is_rest_url_allowed(url: str, policy: dict[str, Any] | None = None) -> bool:
    """Return True when url satisfies the supplied REST fetch policy."""
    try:
        validate_rest_url(url, policy)
    except RestFetchPolicyError:
        return False
    return True


def validate_rest_url(url: str, policy: dict[str, Any] | None = None) -> urllib.parse.ParseResult:
    """Validate url against REST SSRF policy; raise RestFetchPolicyError when blocked."""
    parsed = _parse_url(url)
    host = parsed.hostname
    if host is None:
        raise RestFetchPolicyError("url missing hostname")

    active = policy if isinstance(policy, dict) else default_rest_fetch_policy()
    allowed_hosts = {
        str(item).strip().lower()
        for item in (active.get("allowedHosts") or [])
        if str(item).strip()
    }
    host_lower = host.lower()
    if host_lower in allowed_hosts:
        return parsed

    loopback, private, link_local, metadata = _host_flags(host)
    if metadata and not bool(active.get("allowMetadata")):
        raise RestFetchPolicyError(f"metadata host blocked: {host!r}")
    if link_local and not bool(active.get("allowLinkLocal")):
        raise RestFetchPolicyError(f"link-local host blocked: {host!r}")
    if private and not bool(active.get("allowPrivate")):
        raise RestFetchPolicyError(f"private host blocked: {host!r}")
    if loopback and not bool(active.get("allowLoopback")):
        raise RestFetchPolicyError(f"loopback host blocked: {host!r}")
    if loopback or private or link_local or metadata:
        return parsed
    raise RestFetchPolicyError(f"host not allowlisted: {host!r}")


def is_allowed_recallium_base(url: str) -> bool:
    """Recallium localhost-only guard used by hook rule-fetch scripts."""
    return is_rest_url_allowed(
        url,
        {
            "allowedHosts": list(_DEFAULT_LOOPBACK_HOSTS),
            "allowLoopback": True,
            "allowPrivate": False,
            "allowLinkLocal": False,
            "allowMetadata": False,
        },
    )


def guarded_urlopen(
    url: str,
    policy: dict[str, Any] | None = None,
    *,
    timeout: float = 3,
    method: str = "GET",
    headers: dict[str, str] | None = None,
) -> Any:
    """Open a REST response only after SSRF policy validation."""
    validate_rest_url(url, policy)
    req = urllib.request.Request(url, method=method)
    if headers:
        for key, value in headers.items():
            req.add_header(key, value)
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310


def load_catalog_rest_policy(root: Any, provider_id: str) -> dict[str, Any]:
    """Load REST fetch policy for a registered provider from the catalog."""
    from pathlib import Path

    from memory_provider_catalog import CatalogError, get_provider, load_catalog

    catalog = load_catalog(Path(root))
    try:
        entry = get_provider(catalog, provider_id)
    except CatalogError as exc:
        raise RestFetchPolicyError(str(exc)) from exc
    return rest_fetch_policy_from_catalog_entry(entry)


def fetch_json(url: str, policy: dict[str, Any] | None = None, *, timeout: float = 3) -> Any:
    """Fetch JSON from a policy-validated REST endpoint."""
    try:
        with guarded_urlopen(url, policy, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
    except (URLError, OSError, TimeoutError, UnicodeDecodeError) as exc:
        raise RestFetchPolicyError(f"rest fetch failed: {exc}") from exc
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise RestFetchPolicyError(f"rest response was not JSON: {exc}") from exc
