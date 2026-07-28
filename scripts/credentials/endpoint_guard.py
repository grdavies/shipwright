"""Endpoint allowlist validation before authentication material is attached (PRD 080 phase 3 / R3)."""

from __future__ import annotations

import urllib.parse
from collections.abc import Iterable
from typing import Final

_ALLOWED_SCHEME: Final[str] = "https"


class EndpointGuardError(ValueError):
    """Raised when a destination fails endpoint policy before auth."""


def normalize_allowed_hosts(hosts: Iterable[str] | None) -> frozenset[str]:
    """Return a lower-cased host allowlist."""
    if hosts is None:
        return frozenset()
    return frozenset(str(host).strip().lower() for host in hosts if str(host).strip())


def _parse_destination(url: str) -> urllib.parse.ParseResult:
    if not url or not isinstance(url, str):
        raise EndpointGuardError("url must be a non-empty string")
    try:
        parsed = urllib.parse.urlparse(url.strip())
    except ValueError as exc:
        raise EndpointGuardError(f"invalid url: {url!r}") from exc
    return parsed


def validate_destination(url: str, allowed_hosts: frozenset[str]) -> urllib.parse.ParseResult:
    """Validate a destination URL before any authentication header is attached."""
    parsed = _parse_destination(url)
    if parsed.scheme.lower() != _ALLOWED_SCHEME:
        raise EndpointGuardError(f"only {_ALLOWED_SCHEME} destinations are permitted")
    if parsed.username or parsed.password:
        raise EndpointGuardError("userinfo is not permitted in destination URLs")
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise EndpointGuardError("destination missing hostname")
    if host not in allowed_hosts:
        raise EndpointGuardError(f"host not allowlisted: {host!r}")
    return parsed


def validate_redirect_destination(
    *,
    original_url: str,
    redirect_url: str,
    allowed_hosts: frozenset[str],
) -> urllib.parse.ParseResult:
    """Refuse redirects that leave the entry endpoint allowlist."""
    _ = original_url
    return validate_destination(redirect_url, allowed_hosts)
