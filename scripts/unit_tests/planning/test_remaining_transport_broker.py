"""Remaining transport broker adoption tests (PRD 080 20.5 / R1) — Z,O,M,E,S."""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import closeout_ci as ci
import issues_broker
import planning_github_projects_v2 as gp
import planning_store as ps
import planning_visibility as pv
from credentials.config_surface import present_implicit_default_tables
from credentials.model import CredentialRef, Principal, Resolution, ResolutionState, ResolvedToken, Secret


_TEST_VALUE = "unit-test-remaining-transport-broker-value-abcdef"


def _write_config(
    root: Path,
    *,
    issues: dict | None = None,
    host: dict | None = None,
    deliver: dict | None = None,
    projects: bool = False,
) -> None:
    cfg_dir = root / ".cursor"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    store: dict = {
        "backend": "issue-store",
        "projectKey": "demo",
        "storeLocation": {"mode": "separate-project", "owner": "acme", "repo": "planning"},
        "issues": issues or {"provider": "github-issues"},
    }
    if projects:
        store["operatorProjection"] = {
            "githubProjects": {
                "ownerLogin": "acme",
                "projectNumber": 1,
            }
        }
    payload: dict = {
        "projectId": "acme-demo",
        "defaultBaseBranch": "main",
        "host": host
        or {
            "provider": "github",
            "remote": "origin",
            "ssrfAllowlist": ["api.github.com"],
        },
        "planning": {
            "store": store,
        },
    }
    if deliver is not None:
        payload["deliver"] = deliver
    (cfg_dir / "workflow.config.json").write_text(json.dumps(payload), encoding="utf-8")


class TestNoCredential:
    def test_projects_probe_without_credential_is_unavailable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_config(tmp_path, issues={"provider": "github-issues"}, projects=True)
        cfg = ps.load_workflow_config(tmp_path)
        monkeypatch.setattr(gp, "_fixture_enabled", lambda: False)
        monkeypatch.setattr(
            gp,
            "resolve_issues_provider",
            lambda _cfg: {"provider": "github-issues", "supported": True},
        )
        out = gp.probe_projects_scope(tmp_path, cfg)
        assert out["state"] == "projection-unavailable"
        assert out.get("credentialState") in {
            ResolutionState.EXPLICITLY_NO_AUTH.value,
            ResolutionState.UNRESOLVED.value,
        }

    def test_visibility_unresolved_credential_is_inconclusive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_config(
            tmp_path,
            issues={"provider": "github-issues", "tokenEnv": "SW_PLANNING_ISSUES_TOKEN"},
        )
        unresolved = Resolution.unresolved(
            CredentialRef("tokenEnv:SW_PLANNING_ISSUES_TOKEN"),
            reason="missing-token",
        )
        monkeypatch.setattr(pv, "resolve_host_credential", lambda *a, **k: unresolved)
        monkeypatch.setattr(pv, "git_remote_url", lambda *a, **k: "https://github.com/acme/demo.git")
        out = pv.probe_remote_visibility(tmp_path)
        assert out["remoteVisibility"] == "absent"
        assert out["source"] == "probe-inconclusive"

    def test_closeout_without_credential_fails_closed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import deliver_closeout as dc

        dc.record_pr_delivery_mapping(
            tmp_path,
            {
                "prNumber": "1",
                "prdUnitId": "prd-080-credential-repository-isolation",
                "deliverySlug": "credential-repository-isolation",
                "targetBranch": "feat/credential-repository-isolation",
                "headSha": "a" * 40,
                "runSlug": "credential-repository-isolation",
            },
        )
        event = {
            "ref": "refs/heads/main",
            "after": "b" * 40,
            "head_commit": {"id": "b" * 40, "message": "Merge pull request #1"},
            "commits": [],
        }
        event_path = tmp_path / "event.json"
        event_path.write_text(json.dumps(event), encoding="utf-8")
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
        result = ci.run_ci_closeout(tmp_path, mode="mutate")
        assert result["verdict"] == "fail"
        assert result["error"] == "planning-token-missing"
        assert "credentialRef" in result


class TestOneTransport:
    def test_projects_probe_with_resolved_credential(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_config(
            tmp_path,
            issues={"provider": "github-issues", "credentialRef": "github-issues-work"},
            projects=True,
        )
        credential = Resolution.resolved(
            CredentialRef("github-issues-work"),
            ResolvedToken(Secret(_TEST_VALUE), Principal(profile="work")),
        )
        monkeypatch.setattr(gp, "_credential_for_probe", lambda *a, **k: credential)
        monkeypatch.setattr(gp, "_fixture_enabled", lambda: False)
        captured: dict[str, object] = {}

        def fake_request(method, url, headers, body=None, *, root=None, issues_provider=None, timeout=30):
            captured["headers"] = dict(headers)
            return 200, {"x-oauth-scopes": "read:project, repo"}, b"{}"

        monkeypatch.setattr(gp.issues_http, "request", fake_request, raising=False)
        monkeypatch.setattr(
            gp,
            "resolve_issues_provider",
            lambda _cfg: {"provider": "github-issues", "supported": True},
        )
        cfg = ps.load_workflow_config(tmp_path)
        out = gp.probe_projects_scope(tmp_path, cfg)
        assert out["state"] == "available"
        assert captured["headers"].get("Authorization") == f"Bearer {_TEST_VALUE}"


class TestAllFourTransports:
    @pytest.mark.parametrize(
        "module_name",
        [
            "planning_github_projects_v2",
            "planning_visibility",
            "closeout_ci",
            "planning-doctor",
        ],
    )
    def test_all_four_remaining_transports_import_broker_helpers(self, module_name: str) -> None:
        module = importlib.import_module(module_name)
        if module_name == "planning_github_projects_v2":
            assert hasattr(module, "resolve_issues_credential") or hasattr(module, "_credential_for_probe")
        elif module_name == "planning_visibility":
            assert hasattr(module, "resolve_host_credential")
        elif module_name == "closeout_ci":
            assert hasattr(module, "resolve_planning_credential")
            assert hasattr(module, "apply_closeout_planning_credential")
        else:
            assert hasattr(module, "classify_issue_store_probe")


class TestEndpointRefusal:
    def test_visibility_unresolved_never_yields_auth_success_verdict(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_config(tmp_path, issues={"provider": "github-issues", "tokenEnv": "SW_PLANNING_ISSUES_TOKEN"})
        unresolved = Resolution.unresolved(
            CredentialRef("tokenEnv:SW_PLANNING_ISSUES_TOKEN"),
            reason="missing-token",
        )
        monkeypatch.setattr(pv, "resolve_host_credential", lambda *a, **k: unresolved)
        monkeypatch.setattr(pv, "git_remote_url", lambda *a, **k: "https://github.com/acme/demo.git")
        out = pv._github_repo_private(tmp_path, "acme", "demo", {"provider": "github"}, "github")
        assert out is None


class TestCloseoutSanitizedChildEnv:
    def test_closeout_retains_auth_through_sanitized_child_environment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_config(
            tmp_path,
            issues={"provider": "github-issues", "tokenEnv": "SW_PLANNING_ISSUES_TOKEN"},
        )
        monkeypatch.setenv("SW_PLANNING_ISSUES_TOKEN", _TEST_VALUE)
        cfg = ps.load_workflow_config(tmp_path)
        credential, child_env = ci.apply_closeout_planning_credential(tmp_path, cfg, parent={})
        assert credential.state is ResolutionState.RESOLVED
        assert child_env.get("SW_PLANNING_ISSUES_TOKEN") == _TEST_VALUE
        assert "GITHUB_TOKEN" not in child_env
        assert "GH_TOKEN" not in child_env

    def test_closeout_hardcoded_defaults_removed(self) -> None:
        present = present_implicit_default_tables()
        assert "closeout_ci.hardcoded_token_env_defaults" not in present

    def test_closeout_control_layer_is_explicit(self, tmp_path: Path) -> None:
        _write_config(tmp_path)
        cfg = ps.load_workflow_config(tmp_path)
        layer = ci.resolve_closeout_control_layer(tmp_path, cfg)
        assert layer.get("layer") == "explicit-backend-override"
        assert layer.get("forcedFallback") is False


class TestDoctorCredentialReference:
    def test_doctor_reports_credential_reference_not_secret(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_config(
            tmp_path,
            issues={"provider": "github-issues", "credentialRef": "github-issues-work"},
        )
        doc = importlib.import_module("planning-doctor")
        credential = Resolution.unresolved(
            CredentialRef("github-issues-work"),
            reason="missing-token",
        )
        monkeypatch.setattr(
            ps,
            "resolve_issues_credential",
            lambda *a, **k: credential,
        )
        finding = doc.classify_issue_store_probe(
            {
                "verdict": "fail",
                "error": "credential-unresolved",
                "provider": "github-issues",
                "credentialRef": str(credential.ref),
                "credentialState": credential.state.value,
            }
        )
        assert finding["check"] == "store-token-absent"
        assert finding["credentialRef"] == "github-issues-work"
        assert _TEST_VALUE not in json.dumps(finding)
