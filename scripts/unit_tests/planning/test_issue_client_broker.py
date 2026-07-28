"""Issue-store client broker adoption tests (PRD 080 19.5 / R1) — Z,O,M,E,I."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from credentials.config_surface import present_implicit_default_tables
from credentials.model import CredentialRef, Principal, Resolution, ResolutionState, ResolvedToken, Secret
import issues_broker
import planning_github_client as github_client
import planning_gitlab_client as gitlab_client
import planning_jira_client as jira_client
import planning_linear_client as linear_client
import planning_store as ps


_TEST_VALUE = "unit-test-issue-client-broker-value-abcdef"


def _write_config(root: Path, *, issues: dict, host: dict | None = None) -> None:
    cfg_dir = root / ".cursor"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    payload: dict = {
        "projectId": "acme-demo",
        "host": host
        or {
            "provider": "github",
            "remote": "origin",
            "ssrfAllowlist": ["api.github.com", "gitlab.com", "api.linear.app", "fixture.atlassian.net"],
        },
        "planning": {
            "store": {
                "backend": "issue-store",
                "projectKey": "demo",
                "storeLocation": {"mode": "separate-project", "owner": "acme", "repo": "planning"},
                "issues": issues,
            }
        },
    }
    (cfg_dir / "workflow.config.json").write_text(json.dumps(payload), encoding="utf-8")


class TestNoCredential:
    def test_no_credential_is_explicitly_no_auth_without_default_table(self, tmp_path: Path) -> None:
        assert not hasattr(ps, "DEFAULT_ISSUES_TOKEN_ENV")
        _write_config(tmp_path, issues={"provider": "github-issues"})
        resolution = ps.resolve_issues_credential(tmp_path, issues_provider="github-issues")
        assert resolution.state is ResolutionState.EXPLICITLY_NO_AUTH
        assert "ISSUES_GITHUB_TOKEN" not in (resolution.ref.value,)


class TestOneClient:
    def test_one_github_client_attaches_bearer_via_broker(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_config(
            tmp_path,
            issues={"credentialRef": "github-issues-work"},
            host={
                "provider": "github",
                "remote": "origin",
                "apiBaseUrl": "https://api.github.com",
                "ssrfAllowlist": ["api.github.com"],
            },
        )
        credential = Resolution.resolved(
            CredentialRef("github-issues-work"),
            ResolvedToken(Secret(_TEST_VALUE), Principal(profile="work")),
        )
        captured: dict[str, object] = {}

        def fake_json(method, url, headers, payload=None, *, root=None, issues_provider=None, timeout=30):
            captured["headers"] = dict(headers)
            captured["url"] = url
            return {}

        monkeypatch.setattr(github_client.issues_http, "http_json", fake_json)

        client = github_client.GitHubIssuesClient(tmp_path, credential=credential)
        client._http_json("GET", f"{client.api_base}/repos/acme/planning/issues/1", client.headers)
        assert captured["headers"].get("Authorization") == f"Bearer {_TEST_VALUE}"


class TestAllFourClients:
    @pytest.mark.parametrize(
        ("provider", "factory", "endpoint_host"),
        [
            ("github-issues", "github", "api.github.com"),
            ("gitlab-issues", "gitlab", "gitlab.com"),
            ("jira", "jira", "fixture.atlassian.net"),
            ("linear", "linear", "api.linear.app"),
        ],
    )
    def test_all_four_clients_accept_credential_objects(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        provider: str,
        factory: str,
        endpoint_host: str,
    ) -> None:
        assert not hasattr(ps, "DEFAULT_ISSUES_TOKEN_ENV")
        assert not hasattr(linear_client, "DEFAULT_TOKEN_ENV")

        issues: dict = {"credentialRef": f"{provider}-work"}
        if provider == "jira":
            issues.update(
                {
                    "endpoint": "https://fixture.atlassian.net",
                    "flavor": "dc",
                    "issueType": "Task",
                }
            )
        if provider == "linear":
            issues["teamKey"] = "ENG"

        _write_config(
            tmp_path,
            issues=issues,
            host={
                "provider": "github" if provider != "gitlab-issues" else "gitlab",
                "remote": "origin",
                "ssrfAllowlist": [endpoint_host, "api.github.com", "gitlab.com"],
                "apiBaseUrl": f"https://{endpoint_host}" if provider != "jira" else None,
            },
        )
        # Drop null apiBaseUrl
        cfg_path = tmp_path / ".cursor" / "workflow.config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        if cfg["host"].get("apiBaseUrl") is None:
            cfg["host"].pop("apiBaseUrl", None)
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

        credential = Resolution.resolved(
            CredentialRef(f"{provider}-work"),
            ResolvedToken(Secret(_TEST_VALUE), Principal(profile="work", account="user@example.com")),
        )

        if factory == "github":
            client = github_client.GitHubIssuesClient(tmp_path, credential=credential)
            assert client._token == _TEST_VALUE
        elif factory == "gitlab":
            client = gitlab_client.GitLabIssuesClient(tmp_path, credential=credential)
            assert client._token == _TEST_VALUE
        elif factory == "jira":
            monkeypatch.setattr(
                jira_client,
                "resolve_jira_api_project_key",
                lambda cfg, token, root: "DEMO",
            )
            client = jira_client.JiraIssuesClient(tmp_path, credential=credential)
            assert client._token == _TEST_VALUE
            assert client._bearer_token == _TEST_VALUE  # dc flavor
        else:
            client = linear_client.LinearIssuesClient(tmp_path, credential=credential, cfg=cfg)
            assert client._token == _TEST_VALUE


class TestOutOfScopeEndpoint:
    def test_out_of_scope_endpoint_refuses_before_authorization_header(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_config(
            tmp_path,
            issues={"credentialRef": "gitlab-work"},
            host={
                "provider": "gitlab",
                "remote": "origin",
                "apiBaseUrl": "https://gitlab.com/api/v4",
                "ssrfAllowlist": ["gitlab.com"],
            },
        )
        credential = Resolution.resolved(
            CredentialRef("gitlab-work"),
            ResolvedToken(Secret(_TEST_VALUE)),
        )
        called = {"transport": False}

        def boom(*args: object, **kwargs: object) -> None:
            called["transport"] = True
            raise AssertionError("HTTP transport must not run after endpoint refusal")

        monkeypatch.setattr(gitlab_client.issues_http, "http_request", boom)
        monkeypatch.setattr(gitlab_client.issues_http, "http_json", boom)

        client = gitlab_client.GitLabIssuesClient(tmp_path, credential=credential)
        with pytest.raises(issues_broker.IssuesBrokerError) as exc:
            client._http_json("GET", "https://evil.example.com/api/v4/projects/1", client.headers)
        assert exc.value.code == "endpoint-refused"
        assert called["transport"] is False


class TestImplicitDefaultAbsent:
    def test_implicit_issues_default_table_deleted(self) -> None:
        module = importlib.import_module("planning_store")
        assert not hasattr(module, "DEFAULT_ISSUES_TOKEN_ENV")
        present = present_implicit_default_tables()
        assert "planning_store.DEFAULT_ISSUES_TOKEN_ENV" not in present
        assert not hasattr(linear_client, "DEFAULT_TOKEN_ENV")
