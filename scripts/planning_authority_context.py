#!/usr/bin/env python3
"""PRD 082 phase 4 — PRD 080 input-contract adapter for planning authority (R26)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from credentials.model import Principal

import planning_authority as pa
import planning_authority_reasons as par

PROBE_VERDICT_RESOLVED = "resolved"
PROBE_VERDICT_EXPLICITLY_NO_AUTH = "explicitly-no-auth"
PROBE_VERDICT_UNRESOLVED = "unresolved"
PROBE_VERDICT_TIMEOUT = "timeout"

ALLOWED_PROBE_VERDICTS = frozenset(
    {
        PROBE_VERDICT_RESOLVED,
        PROBE_VERDICT_EXPLICITLY_NO_AUTH,
        PROBE_VERDICT_UNRESOLVED,
        PROBE_VERDICT_TIMEOUT,
    }
)

_PUBLISHED_ENVELOPE_KEYS = frozenset(
    {
        "version",
        "root",
        "projectId",
        "worktreeId",
        "planningAuthority",
        "credentialRefs",
        "memoryNamespace",
        "policyOverrides",
        "runId",
        "remote",
        "repoSlug",
        "destinationEndpoint",
    }
)


@dataclass(frozen=True)
class AuthorityContextSignals:
    """Runtime signals derived from PRD 080 probe + principal inputs only."""

    identity_mismatch: bool = False
    ambiguous: bool = False
    offline: bool = False
    cache_available: bool = False
    authority_state_hint: str | None = None
    reason_hint: str | None = None


def validate_envelope(envelope: dict[str, Any]) -> None:
    unknown = sorted(set(envelope) - _PUBLISHED_ENVELOPE_KEYS)
    if unknown:
        raise ValueError(f"envelope contains unpublished keys: {', '.join(unknown)}")


def configured_backend_from_envelope(envelope: dict[str, Any]) -> str:
    """Derive configured backend id from the published planningAuthority field."""
    validate_envelope(envelope)
    authority = str(envelope.get("planningAuthority") or "none").strip()
    if not authority or authority == "none":
        return "in-repo-public"
    backend, _, _provider = authority.partition(":")
    return backend or "in-repo-public"


def map_probe_verdict(
    probe_verdict: str,
    *,
    principal: Principal | None = None,
    bound_principal: Principal | None = None,
) -> AuthorityContextSignals:
    """Map PRD 080 probe taxonomy to authority runtime signals."""
    verdict = str(probe_verdict or "").strip()
    if verdict not in ALLOWED_PROBE_VERDICTS:
        raise ValueError(f"unsupported probe verdict: {probe_verdict!r}")
    if verdict == PROBE_VERDICT_RESOLVED:
        if principal is not None and bound_principal is not None:
            if principal.profile != bound_principal.profile or principal.account != bound_principal.account:
                return AuthorityContextSignals(
                    identity_mismatch=True,
                    authority_state_hint="blocked",
                    reason_hint=par.REASON_IDENTITY_MISMATCH,
                )
        return AuthorityContextSignals(authority_state_hint="online")
    if verdict == PROBE_VERDICT_EXPLICITLY_NO_AUTH:
        return AuthorityContextSignals(
            authority_state_hint="read-only",
            reason_hint=par.REASON_STORE_UNAVAILABLE,
        )
    if verdict == PROBE_VERDICT_TIMEOUT:
        return AuthorityContextSignals(
            offline=True,
            cache_available=False,
            authority_state_hint="blocked",
            reason_hint=par.REASON_STORE_UNAVAILABLE,
        )
    return AuthorityContextSignals(
        ambiguous=verdict == PROBE_VERDICT_UNRESOLVED,
        offline=verdict == PROBE_VERDICT_UNRESOLVED,
        cache_available=False,
        authority_state_hint="blocked",
        reason_hint=par.REASON_AMBIGUOUS_AUTHORITY
        if verdict == PROBE_VERDICT_UNRESOLVED
        else par.REASON_STORE_UNAVAILABLE,
    )


def authority_from_context(
    envelope: dict[str, Any],
    *,
    probe_verdict: str,
    principal: Principal | None = None,
    bound_principal: Principal | None = None,
    override: str | None = None,
) -> pa.AuthorityDecision:
    """Build an authority decision from published envelope + probe inputs only."""
    validate_envelope(envelope)
    configured = configured_backend_from_envelope(envelope)
    signals = map_probe_verdict(
        probe_verdict,
        principal=principal,
        bound_principal=bound_principal,
    )
    cfg = {
        "planning": {
            "store": {
                "backend": override or configured,
            }
        }
    }
    root = envelope.get("root")
    if not isinstance(root, str) or not root.strip():
        raise ValueError("envelope root is required")
    from pathlib import Path

    return pa.resolve_authority(
        Path(root),
        cfg,
        override=override,
        offline=signals.offline,
        cache_available=signals.cache_available,
        identity_mismatch=signals.identity_mismatch,
        ambiguous=signals.ambiguous,
    )
