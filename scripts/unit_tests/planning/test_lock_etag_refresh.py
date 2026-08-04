"""Lock ETag re-fetch regression (PRD 093 R1, R6)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from issues_lib import IssueRevisionConflict
from planning_canonical import FROZEN_LABEL, compute_etag
import planning_github_client as gc


def _issue_payload(
    *,
    number: int = 42,
    updated_at: str,
    labels: list[str] | None = None,
    locked: bool = False,
) -> dict:
    label_objs = [{"name": name} for name in (labels or ["sw:project:shipwright-planning"])]
    return {
        "number": number,
        "title": "fixture issue",
        "body": "<!-- sw-unit-id: u1 -->\nbody",
        "state": "open",
        "labels": label_objs,
        "updated_at": updated_at,
        "locked": locked,
    }


def _github_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> gc.GitHubIssuesClient:
    monkeypatch.setenv("ISSUES_GITHUB_TOKEN", "token")
    cfg = {
        "planning": {
            "store": {
                "projectKey": "shipwright-planning",
                "storeLocation": {
                    "mode": "separate-project",
                    "owner": "grdavies",
                    "repo": "shipwright-planning",
                },
                "issues": {"tokenEnv": "ISSUES_GITHUB_TOKEN"},
            }
        },
        "host": {"provider": "github"},
    }
    monkeypatch.setattr(gc, "load_workflow_config", lambda _root: cfg)
    return gc.GitHubIssuesClient(tmp_path)


def test_lock_re_fetches_etag_after_put_lock(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import issues_http

    pre_lock = _issue_payload(updated_at="2026-01-01T00:00:00Z", locked=False)
    post_lock = _issue_payload(updated_at="2026-01-01T00:00:01Z", locked=True)
    post_label = _issue_payload(
        updated_at="2026-01-01T00:00:02Z",
        locked=True,
        labels=["sw:project:shipwright-planning", FROZEN_LABEL],
    )
    pre_etag = compute_etag(
        pre_lock["updated_at"],
        pre_lock["body"],
        pre_lock["title"],
        [item["name"] for item in pre_lock["labels"]],
    )
    get_payloads = [pre_lock, post_lock, post_lock, post_label]
    get_index = {"n": 0}
    calls: list[tuple[str, str]] = []

    def fake_urlopen(req, timeout=30):
        method = req.method
        url = req.full_url
        calls.append((method, url))
        if method == "GET" and "/issues/42/parent" in url:
            return MagicMock(
                status=404,
                headers={},
                read=lambda: b"{}",
                __enter__=lambda s: s,
                __exit__=lambda *a: None,
            )
        if method == "GET" and "/issues/42" in url and "/comments" not in url:
            payload = get_payloads[min(get_index["n"], len(get_payloads) - 1)]
            get_index["n"] += 1
            body = json.dumps(payload)
            return MagicMock(
                status=200,
                headers={},
                read=lambda b=body: b.encode(),
                __enter__=lambda s: s,
                __exit__=lambda *a: None,
            )
        if method == "GET" and "/issues/42/comments" in url:
            return MagicMock(
                status=200,
                headers={},
                read=lambda: b"[]",
                __enter__=lambda s: s,
                __exit__=lambda *a: None,
            )
        if method == "PUT" and "/issues/42/lock" in url:
            return MagicMock(
                status=204,
                headers={},
                read=lambda: b"",
                __enter__=lambda s: s,
                __exit__=lambda *a: None,
            )
        if method == "POST" and "/issues/42/labels" in url:
            return MagicMock(
                status=200,
                headers={},
                read=lambda: b"[]",
                __enter__=lambda s: s,
                __exit__=lambda *a: None,
            )
        raise AssertionError(f"unexpected request: {method} {url}")

    monkeypatch.setattr(issues_http, "_urlopen", fake_urlopen)
    client = _github_client(tmp_path, monkeypatch)

    result = client.lock("42", if_match=pre_etag)

    assert FROZEN_LABEL in result.labels
    assert result.locked is True
    assert any(method == "PUT" and "/lock" in url for method, url in calls)
    assert get_index["n"] >= 3


def test_lock_stale_if_match_raises_revision_conflict(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import issues_http

    current = _issue_payload(updated_at="2026-01-02T00:00:00Z", locked=False)
    stale_etag = compute_etag(
        "2026-01-01T00:00:00Z",
        current["body"],
        current["title"],
        [item["name"] for item in current["labels"]],
    )

    def fake_urlopen(req, timeout=30):
        method = req.method
        url = req.full_url
        if method == "GET" and "/issues/42/parent" in url:
            return MagicMock(
                status=404,
                headers={},
                read=lambda: b"{}",
                __enter__=lambda s: s,
                __exit__=lambda *a: None,
            )
        if method == "GET" and "/issues/42" in url and "/comments" not in url:
            body = json.dumps(current)
            return MagicMock(
                status=200,
                headers={},
                read=lambda b=body: b.encode(),
                __enter__=lambda s: s,
                __exit__=lambda *a: None,
            )
        if method == "GET" and "/issues/42/comments" in url:
            return MagicMock(
                status=200,
                headers={},
                read=lambda: b"[]",
                __enter__=lambda s: s,
                __exit__=lambda *a: None,
            )
        raise AssertionError(f"unexpected request: {method} {url}")

    monkeypatch.setattr(issues_http, "_urlopen", fake_urlopen)
    client = _github_client(tmp_path, monkeypatch)

    with pytest.raises(IssueRevisionConflict):
        client.lock("42", if_match=stale_etag)
