"""PRD 344 phase 3 — rate-limit / timeout fixture for PRD 337 post-merge projection (R1, R2).

Reproduces the post-merge INDEX/completion projection hang observed after PRD 337
(` /sw-retro --post-merge` → `set-index-status` / `append-completion` stalling on
GitHub issue search) using hermetic 429 and timeout mocks instead of a live API.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import issues_github
import issues_http
import projection_state as ps
import wave_living_docs as living
from issues_lib import IssueRateLimited


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "test"],
        cwd=path,
        check=True,
        capture_output=True,
    )


def _write_issues_config(root: Path, *, rate_limit: dict[str, Any] | None = None) -> None:
    cfg_dir = root / ".cursor"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    issues: dict[str, Any] = {"provider": "github-issues"}
    if rate_limit is not None:
        issues["rateLimit"] = rate_limit
    payload = {
        "projectId": "prd337-post-merge",
        "host": {
            "provider": "github",
            "remote": "origin",
            "ssrfAllowlist": ["api.github.com"],
        },
        "planning": {
            "store": {
                "backend": "issue-store",
                "projectKey": "planning",
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


@pytest.fixture()
def prd337_post_merge_rate_limit_scenario(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    """Fixture simulating the PRD 337 post-merge rate-limited projection scenario.

    Mirrors primary-checkout INDEX/completion projection under issue-store search
    pressure: tight search timeout + 429 budget, ambient deliver env cleared, and
    helpers to install timeout / persistent-429 transports.
    """
    root = tmp_path / "primary"
    root.mkdir()
    _git_init(root)
    for key in (
        "SW_ORCHESTRATOR_WORKTREE",
        "SW_REPO_ROOT",
        "SW_ISSUES_SEARCH_TIMEOUT",
    ):
        monkeypatch.delenv(key, raising=False)

    # Bound diagnostics to the PRD success window (~30s actionable halt).
    rate_limit = {
        "jitter": False,
        "searchTimeoutSeconds": 5,
        "baseBackoffMs": 50,
        "capBackoffMs": 50,
        "maxAttempts": 3,
        "searchMaxAttempts": 3,
        "searchMaxCumulativeWaitMs": 200,
    }
    _write_issues_config(root, rate_limit=rate_limit)

    search_url = (
        "https://api.github.com/search/issues"
        "?q=repo:acme/planning+label:sw:prd+337"
    )

    def install_persistent_429() -> None:
        def always_429(_req: object, timeout: int = 30):  # noqa: ANN001
            return _FakeHTTPResponse(
                429,
                '{"message":"API rate limit exceeded"}',
                {"Retry-After": "0", "X-RateLimit-Remaining": "0"},
            )

        monkeypatch.setattr(issues_http, "_urlopen", always_429)

    def install_search_timeout() -> None:
        def boom(_req: object, timeout: int = 30):  # noqa: ANN001
            raise TimeoutError("simulated PRD 337 post-merge search hang")

        monkeypatch.setattr(issues_http, "_urlopen", boom)

    def install_one_429_then_ok(payload: dict[str, Any] | None = None) -> dict[str, int]:
        calls = {"n": 0}
        body = json.dumps(payload or {"total_count": 1, "items": [{"number": 337}]})

        def flaky(_req: object, timeout: int = 30):  # noqa: ANN001
            calls["n"] += 1
            if calls["n"] == 1:
                return _FakeHTTPResponse(
                    429,
                    '{"message":"API rate limit exceeded"}',
                    {"Retry-After": "0"},
                )
            return _FakeHTTPResponse(200, body)

        monkeypatch.setattr(issues_http, "_urlopen", flaky)
        return calls

    return {
        "root": root,
        "search_url": search_url,
        "rate_limit": rate_limit,
        "install_persistent_429": install_persistent_429,
        "install_search_timeout": install_search_timeout,
        "install_one_429_then_ok": install_one_429_then_ok,
        "headers": {"Accept": "application/vnd.github+json"},
    }


def test_fixture_search_timeout_is_bounded(
    prd337_post_merge_rate_limit_scenario: dict[str, Any],
) -> None:
    """R1 / O: slow search raises IssueSearchTimeout (no indefinite hang)."""
    scenario = prd337_post_merge_rate_limit_scenario
    scenario["install_search_timeout"]()
    with pytest.raises(issues_github.IssueSearchTimeout) as excinfo:
        issues_github.search_http_json(
            "GET",
            scenario["search_url"],
            scenario["headers"],
            root=scenario["root"],
            sleep_fn=lambda _s: None,
        )
    assert excinfo.value.timeout_seconds == 5
    assert excinfo.value.retryable is True


def test_fixture_rate_limit_recovers_after_one_429(
    prd337_post_merge_rate_limit_scenario: dict[str, Any],
) -> None:
    """R2 / O: one 429 then success — backoff invoked, projection search completes."""
    scenario = prd337_post_merge_rate_limit_scenario
    calls = scenario["install_one_429_then_ok"]()
    sleeps: list[float] = []
    payload = issues_github.search_http_json(
        "GET",
        scenario["search_url"],
        scenario["headers"],
        root=scenario["root"],
        sleep_fn=sleeps.append,
    )
    assert payload["items"][0]["number"] == 337
    assert calls["n"] == 2
    assert len(sleeps) >= 1


def test_fixture_rate_limit_exhausted_raises(
    prd337_post_merge_rate_limit_scenario: dict[str, Any],
) -> None:
    """R2 / M: persistent 429 exhausts budget → IssueRateLimited (retryable)."""
    scenario = prd337_post_merge_rate_limit_scenario
    scenario["install_persistent_429"]()
    with pytest.raises(IssueRateLimited) as excinfo:
        issues_github.search_http_request(
            "GET",
            scenario["search_url"],
            scenario["headers"],
            root=scenario["root"],
            sleep_fn=lambda _s: None,
        )
    assert excinfo.value.retryable is True
    assert "rate limited" in str(excinfo.value).lower()


def test_prd337_post_merge_projection_halts_with_resume_command(
    prd337_post_merge_rate_limit_scenario: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PRD 337 post-merge reproduction: rate-limit during index → resumeCommand (R1/R2)."""
    scenario = prd337_post_merge_rate_limit_scenario
    repo: Path = scenario["root"]
    scope = ps.projection_scope(prd="337", slug="post-merge-retro", action="reconcile")

    def boom(*_a: Any, **_k: Any) -> dict[str, Any]:
        raise IssueRateLimited(
            "github-issues search API rate limited",
            cumulative_wait_ms=1000,
            reason="rate-limited",
            status_code=429,
            retryable=True,
        )

    monkeypatch.setattr(living, "_run_index_projection_step", boom)
    monkeypatch.setattr(living, "target_merge_detected", lambda *_a, **_k: True)
    monkeypatch.setattr(living, "derive_index_status", lambda *_a, **_k: "complete")
    monkeypatch.setattr(living, "resolve_worktree", lambda root, _args: root)
    monkeypatch.setattr(
        living,
        "prefer_worktree_for_projection",
        lambda root, worktree: (worktree, {"onPrimary": True, "preferred": False}),
    )

    halted: dict[str, Any] = {}

    def fake_fail(error: str, exit_code: int = 2, **extra: Any) -> None:
        halted["error"] = error
        halted["exit_code"] = exit_code
        halted.update(extra)
        raise SystemExit(exit_code)

    monkeypatch.setattr(living, "fail", fake_fail)

    with pytest.raises(SystemExit) as excinfo:
        living._cmd_reconcile_locked(
            repo,
            [],
            {"target": {"slug": "post-merge-retro"}},
            {"slug": "post-merge-retro"},
            "337",
        )
    assert excinfo.value.code == 30
    assert halted.get("resumeCommand")
    assert "living-docs reconcile" in str(halted["resumeCommand"])
    assert halted.get("halt") == "projection-rate-limited"

    loaded = ps.load_projection_state(repo, scope)
    assert loaded["status"] == "interrupted"
    assert loaded["interrupt"]["resumeCommand"] == halted["resumeCommand"]
    assert json.loads(ps.projection_state_path(repo, scope).read_text(encoding="utf-8"))
