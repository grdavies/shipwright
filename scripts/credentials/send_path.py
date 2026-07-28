"""Single broker-owned authenticated send path with endpoint guard first (PRD 080 phase 3 / R3)."""

from __future__ import annotations

import urllib.parse
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from credentials.endpoint_guard import EndpointGuardError, normalize_allowed_hosts, validate_destination
from credentials.endpoint_guard import validate_redirect_destination

TransportFn = Callable[..., Any]
_AUTH_HEADER: Final[str] = "Authorization"


@dataclass(frozen=True, slots=True)
class BrokerSendResult:
    refused: bool
    reason: str | None = None
    url: str | None = None
    headers: Mapping[str, str] = field(default_factory=dict)
    response: Any | None = None


def _join_api_base(api_base: str, path: str = "") -> str:
    base = api_base.strip().rstrip("/")
    suffix = (path or "").strip()
    if not suffix:
        return base
    if not suffix.startswith("/"):
        suffix = f"/{suffix}"
    return f"{base}{suffix}"


def _build_headers(*, bearer_token: str | None, extra: Mapping[str, str] | None) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if extra:
        headers.update({str(key): str(value) for key, value in extra.items()})
    if bearer_token:
        headers[_AUTH_HEADER] = f"Bearer {bearer_token}"
    return headers


def broker_send(
    *,
    api_base: str,
    allowed_hosts: Iterable[str],
    bearer_token: str | None = None,
    path: str = "",
    method: str = "GET",
    extra_headers: Mapping[str, str] | None = None,
    transport: TransportFn | None = None,
    follow_redirects: bool = True,
) -> BrokerSendResult:
    """Send authenticated traffic only after endpoint guard validation succeeds."""
    allowlist = normalize_allowed_hosts(allowed_hosts)
    destination = _join_api_base(api_base, path)
    try:
        validate_destination(destination, allowlist)
    except EndpointGuardError as exc:
        return BrokerSendResult(refused=True, reason=str(exc))

    headers = _build_headers(bearer_token=bearer_token, extra=extra_headers)
    if transport is None:
        return BrokerSendResult(refused=False, url=destination, headers=headers)

    current_url = destination
    redirect_hops = 0
    while True:
        response = transport(current_url, method=method, headers=headers)
        redirect_url = getattr(response, "redirect_url", None)
        if not follow_redirects or not redirect_url:
            return BrokerSendResult(
                refused=False,
                url=current_url,
                headers=headers,
                response=response,
            )

        redirect_hops += 1
        if redirect_hops > 10:
            return BrokerSendResult(refused=True, reason="redirect hop limit exceeded")

        next_url = urllib.parse.urljoin(current_url, redirect_url)
        try:
            validate_redirect_destination(
                original_url=current_url,
                redirect_url=next_url,
                allowed_hosts=allowlist,
            )
        except EndpointGuardError as exc:
            return BrokerSendResult(refused=True, reason=str(exc))

        current_url = next_url


def authorization_header(result: BrokerSendResult) -> str | None:
    """Return the Authorization header only when the send was not refused."""
    if result.refused:
        return None
    return result.headers.get(_AUTH_HEADER)
