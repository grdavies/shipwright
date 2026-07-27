"""Broker resolver entry point (phase 1 stub — full resolver lands in phase 5)."""

from __future__ import annotations

from credentials.model import CredentialRef, Resolution


def resolve(ref: CredentialRef, **context: object) -> Resolution:
    """Return unresolved until selector scope and backends are wired (phase 5)."""
    _ = context
    if ref.is_empty:
        return Resolution.unresolved(ref, reason="empty-reference")
    return Resolution.unresolved(ref, reason="resolver-not-configured")
