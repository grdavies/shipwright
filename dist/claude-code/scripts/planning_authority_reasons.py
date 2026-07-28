#!/usr/bin/env python3
"""PRD 082 phase 3 — fallback-reason → authority-state policy matrix (R26)."""

from __future__ import annotations

from typing import Any, Literal

import planning_store as ps

AuthorityState = Literal["online", "read-only", "blocked"]
WriteDisposition = Literal["accept", "refuse-substantive", "refuse-ledger", "local-only"]
CacheValidity = Literal["fresh", "stale", "unavailable"]

REASON_KILL_SWITCH = "kill-switch"
REASON_ISSUES_NONE_OR_UNSUPPORTED = "issues-provider-none-or-unsupported"
REASON_ISSUES_NOT_SHIPPED = "issues-provider-not-shipped"
REASON_HOST_PROVIDER_NONE = "host-provider-none"
REASON_BITBUCKET_ISSUES_UNAVAILABLE = "bitbucket-issues-unavailable"
REASON_OFFLINE_WITH_CACHE = "offline-with-cache"
REASON_OFFLINE_WITHOUT_CACHE = "offline-without-cache"
REASON_STORE_UNAVAILABLE = "store-unavailable"
REASON_IDENTITY_MISMATCH = "identity-mismatch"
REASON_AMBIGUOUS_AUTHORITY = "ambiguous-authority"
REASON_PROJECTION_UNAVAILABLE = "projection-unavailable"

FALLBACK_REASONS = frozenset(
    {
        REASON_KILL_SWITCH,
        REASON_ISSUES_NONE_OR_UNSUPPORTED,
        REASON_ISSUES_NOT_SHIPPED,
        REASON_HOST_PROVIDER_NONE,
        REASON_BITBUCKET_ISSUES_UNAVAILABLE,
        REASON_OFFLINE_WITH_CACHE,
        REASON_OFFLINE_WITHOUT_CACHE,
        REASON_STORE_UNAVAILABLE,
        REASON_IDENTITY_MISMATCH,
        REASON_AMBIGUOUS_AUTHORITY,
        REASON_PROJECTION_UNAVAILABLE,
    }
)

_BLOCKED_REASONS = frozenset(
    {
        REASON_ISSUES_NONE_OR_UNSUPPORTED,
        REASON_ISSUES_NOT_SHIPPED,
        REASON_HOST_PROVIDER_NONE,
        REASON_BITBUCKET_ISSUES_UNAVAILABLE,
        REASON_OFFLINE_WITHOUT_CACHE,
        REASON_STORE_UNAVAILABLE,
        REASON_IDENTITY_MISMATCH,
        REASON_AMBIGUOUS_AUTHORITY,
    }
)


def policy_for_reason(reason: str | None) -> dict[str, Any]:
    """Map a fallback reason to authority state, disposition, and cache validity."""
    if not reason:
        return {
            "authorityState": "online",
            "writeDisposition": "accept",
            "cacheValidity": "fresh",
            "guidance": None,
            "markProjectionDirty": False,
        }
    if reason == REASON_KILL_SWITCH:
        return {
            "authorityState": "read-only",
            "writeDisposition": "refuse-substantive",
            "cacheValidity": "fresh",
            "guidance": ps.KILL_SWITCH_NOTICE,
            "markProjectionDirty": False,
        }
    if reason in _BLOCKED_REASONS:
        guidance = None
        if reason == REASON_BITBUCKET_ISSUES_UNAVAILABLE:
            guidance = ps.BITBUCKET_ISSUE_STORE_GUIDANCE
        return {
            "authorityState": "blocked",
            "writeDisposition": "refuse-substantive",
            "cacheValidity": "unavailable",
            "guidance": guidance,
            "markProjectionDirty": False,
        }
    if reason == REASON_OFFLINE_WITH_CACHE:
        return {
            "authorityState": "read-only",
            "writeDisposition": "refuse-substantive",
            "cacheValidity": "stale",
            "guidance": None,
            "markProjectionDirty": False,
        }
    if reason == REASON_PROJECTION_UNAVAILABLE:
        return {
            "authorityState": "online",
            "writeDisposition": "refuse-ledger",
            "cacheValidity": "fresh",
            "guidance": None,
            "markProjectionDirty": True,
        }
    return {
        "authorityState": "blocked",
        "writeDisposition": "refuse-substantive",
        "cacheValidity": "unavailable",
        "guidance": None,
        "markProjectionDirty": False,
    }


def resolve_fallback_reason(
    root,
    cfg: dict[str, Any],
    *,
    override: str | None = None,
    offline: bool = False,
    cache_available: bool = False,
    identity_mismatch: bool = False,
    ambiguous: bool = False,
    projection_available: bool = True,
) -> str | None:
    """Derive the active fallback reason from config and runtime signals."""
    if identity_mismatch:
        return REASON_IDENTITY_MISMATCH
    if ambiguous:
        return REASON_AMBIGUOUS_AUTHORITY
    if not projection_available:
        return REASON_PROJECTION_UNAVAILABLE
    if offline:
        return REASON_OFFLINE_WITH_CACHE if cache_available else REASON_OFFLINE_WITHOUT_CACHE

    import planning_backend_control as pbc

    configured = ps.resolve_backend_id(cfg, override=override)
    if override is None and configured != ps.DEFAULT_BACKEND:
        if pbc.is_forced_file_store_fallback(root, cfg, override=override):
            return REASON_KILL_SWITCH
    if configured == "issue-store":
        return ps.issue_store_fallback_reason(root, cfg, override=override)
    return None
