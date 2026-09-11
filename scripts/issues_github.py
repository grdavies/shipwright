#!/usr/bin/env python3
"""GitHub Issues search transport wrappers — bounded timeout + 429 backoff (PRD 344 R1–R2)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request

import issues_http
from host_lib import load_workflow_config
from host_ratelimit import RequestResult, execute_with_retry, normalize_headers

GITHUB_ISSUES_PROVIDER = "github-issues"

# Per-request timeout for GitHub search (R1). Override via env or rateLimit.searchTimeoutSeconds.
DEFAULT_SEARCH_TIMEOUT_SECONDS = 30

# Search-path cumulative retry budget (R2 / PRD success: actionable diagnostics within ~30s).
DEFAULT_SEARCH_MAX_CUMULATIVE_WAIT_MS = 30_000


class IssueSearchTimeout(TimeoutError):
    """GitHub search request exceeded the configured timeout (PRD 344 R1)."""

    def __init__(
        self,
        message: str,
        *,
        timeout_seconds: int,
        retryable: bool = True,
    ) -> None:
        super().__init__(message)
        self.timeout_seconds = timeout_seconds
        self.retryable = retryable


def _issues_section(cfg: dict[str, Any]) -> dict[str, Any]:
    planning = cfg.get("planning") if isinstance(cfg.get("planning"), dict) else {}
    store = planning.get("store") if isinstance(planning.get("store"), dict) else {}
    issues = store.get("issues") if isinstance(store.get("issues"), dict) else {}
    return issues


def _rate_limit_section(cfg: dict[str, Any]) -> dict[str, Any]:
    raw = _issues_section(cfg).get("rateLimit")
    return raw if isinstance(raw, dict) else {}


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None


def resolve_search_timeout_seconds(
    cfg: dict[str, Any] | None = None,
    *,
    root: Path | None = None,
) -> int:
    """Resolve per-request timeout for GitHub search API calls (R1)."""
    env_raw = os.environ.get("SW_ISSUES_SEARCH_TIMEOUT", "").strip()
    env_val = _positive_int(env_raw) if env_raw else None
    if env_val is not None:
        return env_val

    if cfg is None and root is not None:
        cfg = load_workflow_config(root)
    rate = _rate_limit_section(cfg or {})
    for key in ("searchTimeoutSeconds", "timeoutSeconds"):
        parsed = _positive_int(rate.get(key))
        if parsed is not None:
            return parsed
    return DEFAULT_SEARCH_TIMEOUT_SECONDS


def resolve_search_rate_limit(
    cfg: dict[str, Any] | None = None,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    """Resolve retry/backoff config for GitHub search, capped for fast diagnostics (R2)."""
    if cfg is None and root is not None:
        cfg = load_workflow_config(root)
    cfg = cfg or {}
    merged = dict(
        issues_http.resolve_issues_rate_limit(cfg, issues_provider=GITHUB_ISSUES_PROVIDER)
    )
    rate = _rate_limit_section(cfg)

    search_cap = _positive_int(rate.get("searchMaxCumulativeWaitMs"))
    if search_cap is not None:
        merged["maxCumulativeWaitMs"] = search_cap
    else:
        existing = _positive_int(merged.get("maxCumulativeWaitMs")) or DEFAULT_SEARCH_MAX_CUMULATIVE_WAIT_MS
        merged["maxCumulativeWaitMs"] = min(existing, DEFAULT_SEARCH_MAX_CUMULATIVE_WAIT_MS)

    overrides = (
        ("searchMaxAttempts", "maxAttempts"),
        ("searchBaseBackoffMs", "baseBackoffMs"),
        ("searchCapBackoffMs", "capBackoffMs"),
    )
    for src, dest in overrides:
        parsed = _positive_int(rate.get(src))
        if parsed is not None:
            merged[dest] = parsed

    if "jitter" in rate:
        merged["jitter"] = bool(rate["jitter"])
    return merged


def search_http_request(
    method: str,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any] | list[Any] | None = None,
    *,
    root: Path,
    timeout: int | None = None,
    rate_limit: dict[str, Any] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> tuple[int, dict[str, str], str]:
    """HTTP request for GitHub search with configurable timeout and 429 backoff (R1, R2)."""
    cfg = load_workflow_config(root)
    timeout_s = timeout if timeout is not None else resolve_search_timeout_seconds(cfg, root=root)
    config = rate_limit if rate_limit is not None else resolve_search_rate_limit(cfg, root=root)
    provider = issues_http.issues_ratelimit_provider(GITHUB_ISSUES_PROVIDER)
    data = json.dumps(payload).encode("utf-8") if payload is not None else None

    def request_fn() -> RequestResult:
        req = Request(url, data=data, headers=headers, method=method)
        try:
            with issues_http._urlopen(req, timeout=timeout_s) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                hdrs = normalize_headers({k: v for k, v in resp.headers.items()})
                return RequestResult(resp.status, hdrs, raw)
        except TimeoutError as exc:
            raise IssueSearchTimeout(
                f"GitHub search timed out after {timeout_s}s: {url}",
                timeout_seconds=timeout_s,
            ) from exc
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            hdrs = normalize_headers({k: v for k, v in exc.headers.items()})
            return RequestResult(exc.code, hdrs, raw)
        except URLError as exc:
            reason = exc.reason
            if isinstance(reason, TimeoutError) or (
                reason is not None and "timed out" in str(reason).lower()
            ):
                raise IssueSearchTimeout(
                    f"GitHub search timed out after {timeout_s}s: {url}",
                    timeout_seconds=timeout_s,
                ) from exc
            raise ConnectionError(str(reason)) from exc

    outcome = execute_with_retry(
        provider=provider,
        config=config,
        method=method,
        request_fn=request_fn,
        sleep_fn=sleep_fn,
    )
    if outcome.verdict == "rate-limited":
        from issues_lib import IssueRateLimited

        raise IssueRateLimited(
            f"{GITHUB_ISSUES_PROVIDER} search API rate limited ({outcome.reason})",
            cumulative_wait_ms=outcome.cumulative_wait_ms or 0,
            reason=outcome.reason or "rate-limited",
            status_code=outcome.status_code,
            retryable=bool(outcome.retryable),
        )
    if outcome.result is None:
        raise RuntimeError(
            f"{GITHUB_ISSUES_PROVIDER} search failed: {outcome.reason or 'unknown'}"
        )
    res = outcome.result
    return res.status_code, res.headers, res.body


def search_http_json(
    method: str,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any] | list[Any] | None = None,
    *,
    root: Path,
    timeout: int | None = None,
    rate_limit: dict[str, Any] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> Any:
    """JSON helper for GitHub search endpoints (R1, R2)."""
    status, _hdrs, body = search_http_request(
        method,
        url,
        headers,
        payload,
        root=root,
        timeout=timeout,
        rate_limit=rate_limit,
        sleep_fn=sleep_fn,
    )
    if status == 404:
        from issues_lib import IssueNotFound

        raise IssueNotFound(f"issue not found: {url}")
    if status >= 400:
        raise RuntimeError(f"HTTP {status}: {body[:300]}")
    return json.loads(body) if body.strip() else {}
