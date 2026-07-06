#!/usr/bin/env python3
"""Rate-limit-aware HTTP transport for issue-store integrations (PRD 043, PRD 026 R35–R42)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from host_lib import DEFAULT_RATE_LIMIT, host_section, load_workflow_config, resolve_rate_limit
from host_ratelimit import RequestResult, execute_with_retry, normalize_headers

# Exposed for unit tests (monkeypatch target).
_urlopen = urlopen

ISSUES_PROVIDER_TO_RATELIMIT = {
    "github-issues": "github",
    "gitlab-issues": "gitlab",
    "jira": "jira",
}


def resolve_issues_rate_limit(cfg: dict[str, Any]) -> dict[str, Any]:
    planning = cfg.get("planning") if isinstance(cfg.get("planning"), dict) else {}
    store = planning.get("store") if isinstance(planning.get("store"), dict) else {}
    issues = store.get("issues") if isinstance(store.get("issues"), dict) else {}
    raw = issues.get("rateLimit")
    merged = dict(DEFAULT_RATE_LIMIT)
    if isinstance(raw, dict):
        for key in DEFAULT_RATE_LIMIT:
            if key in raw:
                merged[key] = raw[key]
        return merged
    return resolve_rate_limit(host_section(cfg))


def issues_ratelimit_provider(issues_provider: str) -> str:
    return ISSUES_PROVIDER_TO_RATELIMIT.get(issues_provider, "github")


def _transport(
    method: str,
    url: str,
    headers: dict[str, str],
    data: bytes | None,
    *,
    root: Path,
    issues_provider: str,
    timeout: int = 30,
) -> tuple[int, dict[str, str], str]:
    cfg = load_workflow_config(root)
    provider = issues_ratelimit_provider(issues_provider)
    config = resolve_issues_rate_limit(cfg)

    def request_fn() -> RequestResult:
        req = Request(url, data=data, headers=headers, method=method)
        try:
            with _urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                hdrs = normalize_headers({k: v for k, v in resp.headers.items()})
                return RequestResult(resp.status, hdrs, raw)
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            hdrs = normalize_headers({k: v for k, v in exc.headers.items()})
            return RequestResult(exc.code, hdrs, raw)
        except URLError as exc:
            raise ConnectionError(str(exc.reason)) from exc

    outcome = execute_with_retry(
        provider=provider,
        config=config,
        method=method,
        request_fn=request_fn,
    )
    if outcome.verdict == "rate-limited":
        from issues_lib import IssueRateLimited

        raise IssueRateLimited(
            f"{issues_provider} API rate limited ({outcome.reason})",
            cumulative_wait_ms=outcome.cumulative_wait_ms or 0,
            reason=outcome.reason or "rate-limited",
            status_code=outcome.status_code,
            retryable=bool(outcome.retryable),
        )
    if outcome.result is None:
        raise RuntimeError(f"{issues_provider} transport failed: {outcome.reason or 'unknown'}")
    res = outcome.result
    return res.status_code, res.headers, res.body


def http_request(
    method: str,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any] | list[Any] | None = None,
    *,
    root: Path,
    issues_provider: str,
    timeout: int = 30,
) -> tuple[int, dict[str, str], str]:
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    return _transport(
        method,
        url,
        headers,
        data,
        root=root,
        issues_provider=issues_provider,
        timeout=timeout,
    )


def http_json(
    method: str,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any] | list[Any] | None = None,
    *,
    root: Path,
    issues_provider: str,
    timeout: int = 30,
) -> Any:
    status, _hdrs, body = http_request(
        method,
        url,
        headers,
        payload,
        root=root,
        issues_provider=issues_provider,
        timeout=timeout,
    )
    if status == 404:
        from issues_lib import IssueNotFound

        raise IssueNotFound(f"issue not found: {url}")
    if status >= 400:
        raise RuntimeError(f"HTTP {status}: {body[:300]}")
    return json.loads(body) if body.strip() else {}


def http_empty(
    method: str,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any] | None = None,
    *,
    root: Path,
    issues_provider: str,
    timeout: int = 30,
    allow_404: bool = False,
) -> None:
    status, _hdrs, body = http_request(
        method,
        url,
        headers,
        payload,
        root=root,
        issues_provider=issues_provider,
        timeout=timeout,
    )
    if status == 404 and allow_404:
        return
    if status >= 400:
        raise RuntimeError(f"HTTP {status}: {body[:300]}")
