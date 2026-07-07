"""Tests for probe_store_host_privacy (gap-029, PRD 057 R14)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import issues_http
import planning_store as ps


def test_probe_store_host_privacy_env_override_requires_ci_context(monkeypatch) -> None:
    """R14 — SW_STORE_HOST_PRIVACY is honored only under an explicit CI-context probe,
    never in an operator's local/interactive run."""
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setenv("SW_STORE_HOST_PRIVACY", "private")
    out = ps.probe_store_host_privacy(Path("/tmp"), {})
    assert out["source"] != "SW_STORE_HOST_PRIVACY"


def test_probe_store_host_privacy_env_override_honored_in_ci(monkeypatch) -> None:
    monkeypatch.setenv("CI", "true")
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
    assert out["source"] == "jiraProjectVisibility"


def test_probe_jira_falls_back_to_live_permission_scheme_probe(monkeypatch, tmp_path: Path) -> None:
    """R14 — jira has no placeholder always-unknown branch: absent `jiraProjectVisibility`
    falls through to a real host-API probe of the project's permission scheme."""

    def fake_request(method, url, headers, root=None, issues_provider=None, timeout=15):
        if url.endswith("/issue/createmeta?projectKeys=PLAN"):
            return 200, {}, json.dumps({"projects": [{"key": "PLAN"}]})
        if url.endswith("/project/PLAN/permissionscheme"):
            return 200, {}, json.dumps(
                {
                    "permissions": [
                        {"permission": "BROWSE_PROJECTS", "holder": {"type": "group", "value": "planning-private"}},
                    ]
                }
            )
        raise AssertionError(url)

    monkeypatch.setattr(issues_http, "http_request", fake_request)
    monkeypatch.setenv("ISSUES_JIRA_TOKEN", "token")
    monkeypatch.setenv("ISSUES_JIRA_EMAIL", "t@t.com")
    cfg = {
        "planning": {
            "store": {
                "issuesProvider": "jira",
                "issues": {"endpoint": "https://example.atlassian.net"},
                "projectKey": "PLAN",
            }
        }
    }
    out = ps.probe_store_host_privacy(tmp_path, cfg)
    assert out["storeHostPrivacy"] == "private"
    assert out["source"] == "host-api"
    assert out["projectKey"] == "PLAN"


def test_probe_jira_public_permission_scheme(monkeypatch, tmp_path: Path) -> None:
    def fake_request(method, url, headers, root=None, issues_provider=None, timeout=15):
        if url.endswith("/issue/createmeta?projectKeys=PLAN"):
            return 200, {}, json.dumps({"projects": [{"key": "PLAN"}]})
        if url.endswith("/project/PLAN/permissionscheme"):
            return 200, {}, json.dumps(
                {
                    "permissions": [
                        {"permission": "BROWSE_PROJECTS", "holder": {"type": "authenticated"}},
                    ]
                }
            )
        raise AssertionError(url)

    monkeypatch.setattr(issues_http, "http_request", fake_request)
    monkeypatch.setenv("ISSUES_JIRA_TOKEN", "token")
    monkeypatch.setenv("ISSUES_JIRA_EMAIL", "t@t.com")
    cfg = {
        "planning": {
            "store": {
                "issuesProvider": "jira",
                "issues": {"endpoint": "https://example.atlassian.net"},
                "projectKey": "PLAN",
            }
        }
    }
    out = ps.probe_store_host_privacy(tmp_path, cfg)
    assert out["storeHostPrivacy"] == "public"
    assert out["source"] == "host-api"


def test_probe_gitlab_issues_never_reached_deferred_provider() -> None:
    """R7/R14 — gitlab-issues is not in SHIPPED_ISSUES_PROVIDERS, so it never reaches
    the shipped-provider probe body at all (no dead always-false branch to exercise)."""
    cfg = {"planning": {"store": {"issuesProvider": "gitlab-issues"}}}
    out = ps.probe_store_host_privacy(Path("/tmp"), cfg)
    assert out["source"] == "issues-provider-none"
    assert out["storeHostPrivacy"] == "public"
