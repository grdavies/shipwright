"""Unit tests for GitHub search timeout + 429 retry wrappers (PRD 344 R1–R2)."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.error import URLError

import pytest

import issues_github
import issues_http
from issues_lib import IssueRateLimited


def _write_config(root: Path, *, rate_limit: dict | None = None) -> None:
    cfg_dir = root / ".cursor"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    issues: dict = {"provider": "github-issues"}
    if rate_limit is not None:
        issues["rateLimit"] = rate_limit
    payload = {
        "projectId": "acme-demo",
        "host": {
            "provider": "github",
            "remote": "origin",
            "ssrfAllowlist": ["api.github.com"],
        },
        "planning": {
            "store": {
                "backend": "issue-store",
                "projectKey": "demo",
                "storeLocation": {
                    "mode": "separate-project",
                    "owner": "acme",
                    "repo": "planning",
                },
                "issues": issues,
            }
        },
    }
    (cfg_dir / "workflow.config.json").write_text(json.dumps(payload), encoding="utf-8")


class _FakeHTTPResponse:
    def __init__(self, status: int, body: str, headers: dict[str, str] | None = None) -> None:
        self.status = status
        self._body = body.encode("utf-8")
        self.headers = headers or {}

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeHTTPResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None



def test_resolve_search_timeout_from_config(tmp_path: Path) -> None:
    _write_config(tmp_path, rate_limit={"searchTimeoutSeconds": 12})
    assert issues_github.resolve_search_timeout_seconds(root=tmp_path) == 12


def test_resolve_search_timeout_env_overrides_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path, rate_limit={"searchTimeoutSeconds": 12})
    monkeypatch.setenv("SW_ISSUES_SEARCH_TIMEOUT", "7")
    assert issues_github.resolve_search_timeout_seconds(root=tmp_path) == 7


def test_search_timeout_raises_issue_search_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R1 / O: one timeout → IssueSearchTimeout with configured seconds."""
    _write_config(tmp_path, rate_limit={"searchTimeoutSeconds": 5, "jitter": False})

    def boom(_req: object, timeout: int = 30):  # noqa: ANN001
        assert timeout == 5
        raise TimeoutError("simulated slow search")

    monkeypatch.setattr(issues_http, "_urlopen", boom)
    with pytest.raises(issues_github.IssueSearchTimeout) as excinfo:
        issues_github.search_http_json(
            "GET",
            "https://api.github.com/search/issues?q=repo:acme/planning",
            {"Accept": "application/vnd.github+json"},
            root=tmp_path,
            sleep_fn=lambda _s: None,
        )
    assert excinfo.value.timeout_seconds == 5
    assert excinfo.value.retryable is True


def test_search_timeout_from_urlerror_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R1 / B: URLError wrapping timed-out reason still maps to IssueSearchTimeout."""
    _write_config(tmp_path, rate_limit={"searchTimeoutSeconds": 3, "jitter": False})

    def boom(_req: object, timeout: int = 30):  # noqa: ANN001
        raise URLError(TimeoutError("The read operation timed out"))

    monkeypatch.setattr(issues_http, "_urlopen", boom)
    with pytest.raises(issues_github.IssueSearchTimeout) as excinfo:
        issues_github.search_http_request(
            "GET",
            "https://api.github.com/search/issues?q=repo:acme/planning",
            {},
            root=tmp_path,
            sleep_fn=lambda _s: None,
        )
    assert excinfo.value.timeout_seconds == 3


def test_search_instant_success_zero_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R1 / Z + R2 / Z: instant 200 — no rate-limit path, payload returned."""
    _write_config(tmp_path, rate_limit={"jitter": False})
    body = json.dumps({"total_count": 1, "items": [{"number": 1}]})

    def ok(_req: object, timeout: int = 30):  # noqa: ANN001
        return _FakeHTTPResponse(200, body)

    monkeypatch.setattr(issues_http, "_urlopen", ok)
    sleeps: list[float] = []
    payload = issues_github.search_http_json(
        "GET",
        "https://api.github.com/search/issues?q=repo:acme/planning",
        {},
        root=tmp_path,
        sleep_fn=sleeps.append,
    )
    assert payload["total_count"] == 1
    assert sleeps == []


def test_search_retries_once_on_429_then_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R2 / O: one 429 then success — exponential backoff invoked once."""
    _write_config(
        tmp_path,
        rate_limit={
            "jitter": False,
            "baseBackoffMs": 100,
            "capBackoffMs": 1000,
            "maxAttempts": 5,
            "searchMaxCumulativeWaitMs": 30_000,
        },
    )
    calls = {"n": 0}

    def flaky(_req: object, timeout: int = 30):  # noqa: ANN001
        calls["n"] += 1
        if calls["n"] == 1:
            return _FakeHTTPResponse(
                429,
                '{"message":"rate limit exceeded"}',
                {"Retry-After": "0"},
            )
        return _FakeHTTPResponse(200, json.dumps({"items": [{"number": 9}]}))

    monkeypatch.setattr(issues_http, "_urlopen", flaky)
    sleeps: list[float] = []
    payload = issues_github.search_http_json(
        "GET",
        "https://api.github.com/search/issues?q=repo:acme/planning",
        {},
        root=tmp_path,
        sleep_fn=sleeps.append,
    )
    assert payload["items"][0]["number"] == 9
    assert calls["n"] == 2
    assert len(sleeps) >= 1


def test_search_rate_limit_exhausted_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R2 / M: repeated 429 exhausts budget → IssueRateLimited (retryable)."""
    _write_config(
        tmp_path,
        rate_limit={
            "jitter": False,
            "baseBackoffMs": 50,
            "capBackoffMs": 50,
            "maxAttempts": 3,
            "searchMaxCumulativeWaitMs": 200,
            "searchMaxAttempts": 3,
        },
    )

    def always_429(_req: object, timeout: int = 30):  # noqa: ANN001
        return _FakeHTTPResponse(429, '{"message":"rate limit exceeded"}')

    monkeypatch.setattr(issues_http, "_urlopen", always_429)
    with pytest.raises(IssueRateLimited) as excinfo:
        issues_github.search_http_request(
            "GET",
            "https://api.github.com/search/issues?q=repo:acme/planning",
            {},
            root=tmp_path,
            sleep_fn=lambda _s: None,
        )
    assert excinfo.value.retryable is True
    assert "rate limited" in str(excinfo.value).lower()


def test_search_rate_limit_caps_cumulative_wait(tmp_path: Path) -> None:
    """Search path caps cumulative wait so diagnostics stay within ~30s (R2)."""
    _write_config(
        tmp_path,
        rate_limit={
            "maxCumulativeWaitMs": 300_000,
            "searchMaxCumulativeWaitMs": 15_000,
        },
    )
    cfg = issues_github.resolve_search_rate_limit(root=tmp_path)
    assert cfg["maxCumulativeWaitMs"] == 15_000
