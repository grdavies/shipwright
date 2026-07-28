"""Legacy classification and release preflight tests (PRD 080 22.5 / R7, R1)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from credentials import failure_codes as fc
from credentials.ci_declaration import ci_selector_path
from credentials.doctor import (
    LegacyClassification,
    classify_legacy_surface,
    release_blocking_alias_preflight,
    remediate,
)
from credentials.config_surface import ResolvedCredentialSurface, resolve_config_surface

_TEST_VALUE = "sk_test_fixture_allowlisted_secret_scan_0123456789"


def _valid_entry(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "backend": "environment",
        "provider": "github",
        "hostname": "github.com",
        "account": "work",
        "allowedRepos": ["owner/repo"],
        "allowedProjectIds": ["proj-1"],
        "allowedEndpoints": ["https://api.github.com"],
    }
    payload.update(overrides)
    return payload


def _write_selector(path: Path, entries: dict[str, dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    path.write_text(json.dumps({"version": 1, "entries": entries}), encoding="utf-8")
    os.chmod(path, 0o600)


def _write_ci_selector(root: Path, entries: dict[str, dict[str, object]]) -> None:
    path = ci_selector_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "entries": entries}), encoding="utf-8")


class TestLegacyClassificationReady:
    def test_credential_ref_with_local_selector_classifies_ready(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        selector = tmp_path / "credential-selector.json"
        _write_selector(selector, {"github-work": _valid_entry()})
        surface = ResolvedCredentialSurface(
            surface="host",
            credential_ref="github-work",
            token_env=None,
            source="credentialRef",
        )
        result = classify_legacy_surface(
            root,
            surface,
            selector_path=selector,
        )
        assert result == LegacyClassification.READY


class TestNeedsLocalSelector:
    def test_credential_ref_without_selector_needs_local_selector(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        surface = ResolvedCredentialSurface(
            surface="host",
            credential_ref="github-work",
            token_env=None,
            source="credentialRef",
        )
        result = classify_legacy_surface(root, surface)
        assert result == LegacyClassification.NEEDS_LOCAL_SELECTOR

    def test_token_env_alias_without_selector_needs_local_selector(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        surface = ResolvedCredentialSurface(
            surface="host",
            credential_ref=None,
            token_env="GITHUB_TOKEN",
            source="tokenEnv-alias",
        )
        result = classify_legacy_surface(root, surface, environ={})
        assert result == LegacyClassification.NEEDS_LOCAL_SELECTOR


class TestNeedsCiDeclaration:
    def test_token_env_on_actions_without_declaration(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        surface = ResolvedCredentialSurface(
            surface="host",
            credential_ref=None,
            token_env="GITHUB_TOKEN",
            source="tokenEnv-alias",
        )
        result = classify_legacy_surface(
            root,
            surface,
            environ={"GITHUB_ACTIONS": "true", "GITHUB_TOKEN": _TEST_VALUE},
        )
        assert result == LegacyClassification.NEEDS_CI_DECLARATION


class TestReleaseBlockingPreflight:
    def test_preflight_refuses_alias_removal_without_local_and_ci(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        result = release_blocking_alias_preflight(
            root=root,
            token_env="GITHUB_TOKEN",
            environ={},
        )
        assert result["aliasRemovalAllowed"] is False
        assert result["verdict"] == "fail"
        assert result["code"] == fc.MISSING_CI_DECLARATION
        assert "remediate" in result["remediationCommand"]

    def test_preflight_allows_alias_removal_when_both_declared(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        selector = tmp_path / "credential-selector.json"
        _write_selector(selector, {"github-work": _valid_entry(backend="environment")})
        _write_ci_selector(root, {"github-work": _valid_entry(backend="environment")})
        result = release_blocking_alias_preflight(
            root=root,
            token_env="GITHUB_TOKEN",
            selector_path=selector,
            environ={"GITHUB_TOKEN": _TEST_VALUE},
        )
        assert result["localDeclared"] is True
        assert result["ciDeclared"] is True
        assert result["aliasRemovalAllowed"] is True
        assert result["verdict"] == "pass"

    def test_ci_remediation_writes_repository_selector(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        result = remediate(
            scope="ci",
            code=fc.MISSING_CI_DECLARATION,
            root=root,
        )
        assert result["verdict"] == "ok"
        path = Path(result["path"])
        assert path == ci_selector_path(root)
        assert path.is_file()


class TestConfigSurfaceClassification:
    def test_legacy_token_env_config_classifies_via_surface(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        cfg = {
            "projectId": "proj-1",
            "host": {"tokenEnv": "GITHUB_TOKEN"},
        }
        surface = resolve_config_surface(cfg)
        classification = classify_legacy_surface(
            root,
            surface.host,
            environ={"GITHUB_TOKEN": _TEST_VALUE},
        )
        assert classification == LegacyClassification.NEEDS_LOCAL_SELECTOR

    def test_absent_surface_is_ready(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        surface = ResolvedCredentialSurface(
            surface="memory",
            credential_ref=None,
            token_env=None,
            source="absent",
        )
        assert classify_legacy_surface(root, surface) == LegacyClassification.READY
