"""Broker credential helpers for memory REST adapters (PRD 080 phase 21 / R1, R3)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from credentials.model import Resolution, ResolutionState, ResolvedToken
from issues_broker import token_from_credential
from sw_recallium_url import RestFetchPolicyError, validate_rest_url


class MemoryBrokerError(RuntimeError):
    """Fail-closed broker refusal for memory REST adapters."""

    def __init__(self, message: str, *, code: str = "broker-error") -> None:
        self.code = code
        super().__init__(message)


def prepare_bound_headers(
    *,
    url: str,
    policy: dict[str, Any],
    credential: Resolution | ResolvedToken | None = None,
    bearer_token: str | None = None,
    extra_headers: Mapping[str, str] | None = None,
    method: str = "GET",
) -> dict[str, str]:
    """Validate destination via REST policy, then return headers (auth only after allowlist)."""
    _ = method
    try:
        validate_rest_url(url, policy)
    except RestFetchPolicyError as exc:
        raise MemoryBrokerError(str(exc), code="endpoint-refused") from exc

    token = bearer_token
    if credential is not None:
        resolved_token, reason = token_from_credential(credential)
        if isinstance(credential, Resolution) and credential.state is ResolutionState.EXPLICITLY_NO_AUTH:
            token = None
        elif reason and reason != "explicitly-no-auth":
            raise MemoryBrokerError(reason, code=reason)
        elif resolved_token:
            token = resolved_token

    headers: dict[str, str] = {"Accept": "application/json"}
    if extra_headers:
        headers.update({str(key): str(value) for key, value in extra_headers.items()})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers
