"""Alias-removal preflight tests (PRD 080 26.4) — Z,O,B,S,E."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from credentials.alias_removal_preflight import run_alias_removal_preflight
from credentials.ci_declaration import ci_selector_path
from credentials.migration_release_gate import (
    TRANSPORTS_NOT_MIGRATED_CODE,
    VERSION_FLOOR_UNPUBLISHED_CODE,
)

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


def test_z_no_proof_refuses_alias_removal(tmp_path: Path) -> None:
    """Z — no local or CI proof refuses alias removal."""
    root = tmp_path / "repo"
    root.mkdir()
    result = run_alias_removal_preflight(
        root,
        token_env="GITHUB_TOKEN",
        environ={},
    )
    assert result["aliasRemovalAllowed"] is False
    assert result["localDeclared"] is False
    assert result["ciDeclared"] is False


def test_o_local_only_refuses_alias_removal(tmp_path: Path) -> None:
    """O — local-only declaration refuses alias removal."""
    root = tmp_path / "repo"
    root.mkdir()
    selector = tmp_path / "credential-selector.json"
    _write_selector(selector, {"github-work": _valid_entry(backend="environment")})
    result = run_alias_removal_preflight(
        root,
        token_env="GITHUB_TOKEN",
        selector_path=selector,
        environ={"GITHUB_TOKEN": _TEST_VALUE},
    )
    assert result["localDeclared"] is True
    assert result["ciDeclared"] is False
    assert result["aliasRemovalAllowed"] is False


def test_b_both_proofs_and_version_floor_allow_alias_removal(
    tmp_path: Path,
) -> None:
    """B — local and CI proofs with published version floor allow alias removal."""
    root = tmp_path / "repo"
    root.mkdir()
    selector = tmp_path / "credential-selector.json"
    _write_selector(selector, {"github-work": _valid_entry(backend="environment")})
    _write_ci_selector(root, {"github-work": _valid_entry(backend="environment")})
    result = run_alias_removal_preflight(
        root,
        token_env="GITHUB_TOKEN",
        selector_path=selector,
        environ={"GITHUB_TOKEN": _TEST_VALUE},
    )
    assert result["localDeclared"] is True
    assert result["ciDeclared"] is True
    assert result["versionFloorPublished"] is True
    assert result["transportsMigrated"] is True
    assert result["aliasRemovalAllowed"] is True
    assert result["verdict"] == "pass"


def test_s_ci_only_refuses_alias_removal(tmp_path: Path) -> None:
    """S — CI-only declaration refuses alias removal."""
    root = tmp_path / "repo"
    root.mkdir()
    _write_ci_selector(root, {"github-work": _valid_entry(backend="environment")})
    result = run_alias_removal_preflight(
        root,
        token_env="GITHUB_TOKEN",
        environ={"GITHUB_ACTIONS": "true", "GITHUB_TOKEN": _TEST_VALUE},
    )
    assert result["localDeclared"] is False
    assert result["ciDeclared"] is True
    assert result["aliasRemovalAllowed"] is False


def test_e_unpublished_version_floor_refuses_alias_removal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E — both proofs without a published version floor refuse alias removal."""
    monkeypatch.setattr(
        "credentials.alias_removal_preflight.is_version_floor_published",
        lambda _root=None: False,
    )
    root = tmp_path / "repo"
    root.mkdir()
    selector = tmp_path / "credential-selector.json"
    _write_selector(selector, {"github-work": _valid_entry(backend="environment")})
    _write_ci_selector(root, {"github-work": _valid_entry(backend="environment")})
    result = run_alias_removal_preflight(
        root,
        token_env="GITHUB_TOKEN",
        selector_path=selector,
        environ={"GITHUB_TOKEN": _TEST_VALUE},
    )
    assert result["localDeclared"] is True
    assert result["ciDeclared"] is True
    assert result["versionFloorPublished"] is False
    assert result["aliasRemovalAllowed"] is False
    assert result["code"] == VERSION_FLOOR_UNPUBLISHED_CODE


def test_transports_incomplete_refuses_alias_removal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E — incomplete enumerated transport migration refuses alias removal."""
    monkeypatch.setattr(
        "credentials.alias_removal_preflight.enumerated_transports_migrated",
        lambda _root=None: (False, ("missing-transport",)),
    )
    root = tmp_path / "repo"
    root.mkdir()
    selector = tmp_path / "credential-selector.json"
    _write_selector(selector, {"github-work": _valid_entry(backend="environment")})
    _write_ci_selector(root, {"github-work": _valid_entry(backend="environment")})
    result = run_alias_removal_preflight(
        root,
        token_env="GITHUB_TOKEN",
        selector_path=selector,
        environ={"GITHUB_TOKEN": _TEST_VALUE},
    )
    assert result["aliasRemovalAllowed"] is False
    assert result["code"] == TRANSPORTS_NOT_MIGRATED_CODE
