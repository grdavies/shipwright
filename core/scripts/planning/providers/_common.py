"""Shared helpers for planning issue provider adapters (PRD 082 phase 13 / R27)."""
from __future__ import annotations

from typing import Any


def probe_rate_limited_result(exc: Exception) -> dict[str, Any] | None:
    from issues_lib import IssueRateLimited

    if not isinstance(exc, IssueRateLimited):
        return None
    return {
        "verdict": "fail",
        "error": "rate-limited",
        "retryable": bool(exc.retryable),
        "reason": exc.reason,
        "cumulativeWaitMs": exc.cumulative_wait_ms,
        "message": str(exc),
    }
