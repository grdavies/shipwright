"""PRD 066 phase 10 — adapter footprint, registration, non-regression (R16, R20, R21)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import issues_http
import issues_lib
import planning_linear_client as plc
import planning_store as ps


def _github_cfg(*, projects_enabled: bool = False) -> dict[str, Any]:
    op: dict[str, Any] = {
        "githubProjects": {"enabled": projects_enabled, "ownerLogin": "acme", "projectNumber": 1}
    }
    op["linear"] = {"enabled": False}
    return {
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "github-issues",
                "projectKey": "planning",
                "issues": {"tokenEnv": "ISSUES_GITHUB_TOKEN"},
                "operatorProjection": op,
            }
        },
        "host": {"provider": "github"},
    }


def _jira_cfg() -> dict[str, Any]:
    return {
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "jira",
                "projectKey": "planning",
                "issues": {
                    "tokenEnv": "ISSUES_JIRA_TOKEN",
                    "endpoint": "https://example.atlassian.net",
                },
                "operatorProjection": {
                    "githubProjects": {"enabled": False},
                    "linear": {"enabled": False},
                },
            }
        },
        "host": {"provider": "none"},
    }


def _file_store_cfg() -> dict[str, Any]:
    return {
        "planning": {
            "store": {
                "backend": "in-repo-public",
                "operatorProjection": {
                    "githubProjects": {"enabled": False},
                    "linear": {"enabled": False},
                },
            }
        }
    }


def _linear_cfg() -> dict[str, Any]:
    return {
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "linear",
                "projectKey": "planning",
                "issues": {
                    "tokenEnv": "ISSUES_LINEAR_TOKEN",
                    "teamKey": "ENG",
                    "teamId": "team_ENG",
                    "authMode": "api-key",
                },
                "operatorProjection": {"linear": {"enabled": True}},
            }
        }
    }


def test_r16_registration_footprint_surface() -> None:
    """R16 — registration touchpoints expose recognition vs shipped + rate maps + index ids."""
    footprint = ps.issues_provider_registration_footprint()
    assert footprint["verdict"] == "ok"
    assert footprint["action"] == "issues-provider-registration"
    assert "github-issues" in footprint["issuesProviders"]
    assert "linear" in footprint["issuesProviders"]
    assert "linear" not in footprint["shippedIssuesProviders"]
    assert footprint["rateLimitMap"]["linear"] == "linear"
    assert footprint["capabilityIndexIds"]["linear"] == "provider.providers.issues.linear"
    assert "scripts/planning_migrate_issue_store.py" in footprint["migrationHooks"]
    assert footprint["linear"]["liveClientWired"] is True
    assert footprint["linear"]["promotionGatedBy"] == ["conformance", "oauth-docs-gate"]


def test_r20_linear_recognized_not_shipped() -> None:
    """R20 — linear in ISSUES_PROVIDERS when wired; SHIPPED promotion gated."""
    assert plc.LIVE_CLIENT is True
    assert "linear" in ps.ISSUES_PROVIDERS
    assert "linear" not in ps.SHIPPED_ISSUES_PROVIDERS
    assert "linear" in issues_http.ISSUES_PROVIDER_TO_RATELIMIT


def test_r20_doctor_refuses_deferred_stub(tmp_path: Path) -> None:
    """R20 — doctor refuses deferred gitlab-issues stub selection."""
    cfg = {
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "gitlab-issues",
                "projectKey": "planning",
            }
        }
    }
    result = ps.doctor_issues_provider_stub(tmp_path, cfg)
    assert result["verdict"] == "fail"
    assert result["error"] == "deferred-provider-stub-refused"


def test_r20_doctor_notes_linear_recognized_not_shipped(tmp_path: Path) -> None:
    """R20 — doctor passes with notice when linear recognized but unshipped."""
    result = ps.doctor_issues_provider_stub(tmp_path, _linear_cfg())
    assert result["verdict"] == "pass"
    assert result["notice"] == "linear-recognized-not-shipped"


def test_r20_linear_live_backend_fail_closed_without_shipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R20 — live IssuesClient refuses unshipped linear (fixture mode still allowed)."""
    monkeypatch.delenv("SW_ISSUES_FIXTURE", raising=False)
    client = issues_lib.IssuesClient(tmp_path, "linear")
    with pytest.raises(issues_lib.IssueCapabilityError) as exc:
        client._live_backend()
    assert "not shipped" in str(exc.value).lower()


def test_r20_linear_issue_store_falls_back_to_file_store(tmp_path: Path) -> None:
    """R20 — issue-store with unshipped linear resolves to in-repo-public."""
    resolved = ps.resolve_effective_backend(tmp_path, _linear_cfg())
    assert resolved["configured"] == "issue-store"
    assert resolved["effective"] == ps.DEFAULT_BACKEND
    assert resolved["fallbackReason"] == "issues-provider-not-shipped"


def test_r21_github_issues_unchanged_when_linear_projects_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R21 — github-issues LCD path unchanged when Linear/Projects projection disabled."""
    cfg = _github_cfg(projects_enabled=False)
    issues = ps.resolve_issues_provider(cfg)
    assert issues["provider"] == "github-issues"
    assert issues["shipped"] is True
    assert ps.issue_store_fallback_reason(tmp_path, cfg) != "issues-provider-not-shipped"
    monkeypatch.setattr(
        ps,
        "resolve_provider",
        lambda _root: {"verdict": "ok", "provider": "github", "remoteUrl": "https://github.com/acme/planning.git"},
    )
    resolved = ps.resolve_effective_backend(tmp_path, cfg)
    assert resolved["configured"] == "issue-store"
    assert resolved["effective"] == "issue-store"
    assert resolved.get("fallback") is not True

    store = issues_lib.FixtureIssuesStore(tmp_path / "gh-fixture.json")
    created = store.create(
        title="[planning] prd:unit-1",
        body="<!-- sw-unit-id: unit-1 -->\nbody",
        labels=["sw:prd"],
        project_key="planning",
        artifact_type="prd",
        unit_id="unit-1",
    )
    got = store.get(created.id)
    assert got.unit_id == "unit-1"
    assert got.title == created.title


def test_r21_jira_unchanged_when_linear_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R21 — jira provider resolution unchanged when Linear projection off."""
    cfg = _jira_cfg()
    issues = ps.resolve_issues_provider(cfg)
    assert issues["provider"] == "jira"
    assert issues["shipped"] is True
    assert ps.issue_store_fallback_reason(tmp_path, cfg) != "issues-provider-not-shipped"
    monkeypatch.setattr(
        ps,
        "resolve_provider",
        lambda _root: {"verdict": "ok", "provider": "github", "remoteUrl": "https://github.com/acme/planning.git"},
    )
    resolved = ps.resolve_effective_backend(tmp_path, cfg)
    assert resolved["configured"] == "issue-store"
    assert resolved["effective"] == "issue-store"
    assert resolved.get("fallback") is not True


def test_r21_file_store_unchanged_when_linear_projects_off(tmp_path: Path) -> None:
    """R21 — in-repo-public file-store default unchanged."""
    cfg = _file_store_cfg()
    resolved = ps.resolve_effective_backend(tmp_path, cfg)
    assert resolved["configured"] == "in-repo-public"
    assert resolved["effective"] == "in-repo-public"
    assert resolved.get("fallback") is not True

    backend = ps.get_backend(tmp_path, cfg)
    assert backend.backend_id == "in-repo-public"


def test_r16_config_schema_has_linear_projection_flags() -> None:
    """R16 — config schema documents Linear team scope + operatorProjection.linear."""
    schema_path = scripts.parent / "core" / "sw-reference" / "config.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    store = schema["properties"]["planning"]["properties"]["store"]["properties"]
    issues = store["issues"]["properties"]
    assert "teamKey" in issues
    assert "teamId" in issues
    assert "authMode" in issues
    linear_op = store["operatorProjection"]["properties"]["linear"]["properties"]
    assert "enabled" in linear_op
    assert "initiativeSubstitute" in linear_op
    assert "budget" in linear_op

    example_path = scripts.parent / "core" / "sw-reference" / "workflow.config.example.json"
    example = json.loads(example_path.read_text(encoding="utf-8"))
    store_ex = example["planning"]["store"]
    assert store_ex["issues"]["teamKey"] == "ENG"
    assert store_ex["operatorProjection"]["linear"]["enabled"] is False
