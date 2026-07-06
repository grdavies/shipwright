"""Tests for probe_store_host_privacy (gap-029)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import planning_store as ps


def test_probe_store_host_privacy_env_override(monkeypatch) -> None:
    monkeypatch.setenv("SW_STORE_HOST_PRIVACY", "private")
    out = ps.probe_store_host_privacy(Path("/tmp"), {})
    assert out["storeHostPrivacy"] == "private"
    assert out["source"] == "SW_STORE_HOST_PRIVACY"


def test_probe_store_host_privacy_config_declared() -> None:
    cfg = {"planning": {"store": {"storeHostPrivacy": "private", "issuesProvider": "github-issues"}}}
    out = ps.probe_store_host_privacy(Path("/tmp"), cfg)
    assert out["storeHostPrivacy"] == "private"
    assert out["source"] == "config-declared"


def test_probe_github_private_store(monkeypatch, tmp_path: Path) -> None:
    import issues_http

    def fake_request(method, url, headers, root=None, issues_provider=None, timeout=15):
        if "/repos/plan-org/planning" in url:
            return 200, {}, json.dumps({"private": True})
        raise AssertionError(url)

    monkeypatch.setattr(issues_http, "http_request", fake_request)
    monkeypatch.setenv("ISSUES_GITHUB_TOKEN", "token")
    cfg = {
        "planning": {
            "store": {
                "issuesProvider": "github-issues",
                "storeLocation": {"mode": "separate-project", "owner": "plan-org", "repo": "planning"},
            }
        },
        "host": {"provider": "github"},
    }
    out = ps.probe_store_host_privacy(tmp_path, cfg)
    assert out["storeHostPrivacy"] == "private"
    assert out["source"] == "host-api"
    assert ps.issue_store_private_enough(cfg, tmp_path) is True


def test_probe_jira_private_project() -> None:
    cfg = {
        "planning": {
            "store": {
                "issuesProvider": "jira",
                "jiraProjectVisibility": "private",
            }
        }
    }
    out = ps.probe_store_host_privacy(Path("/tmp"), cfg)
    assert out["storeHostPrivacy"] == "private"
