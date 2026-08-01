"""Adapter credential isolation tests (PRD 080 11.4 / R5)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from credentials.model import CredentialRef, Resolution, ResolutionState, ResolvedToken, Secret

CORE_HOOKS = Path(__file__).resolve().parents[3] / "core" / "hooks"


def _load_guardrail_core():
    path = CORE_HOOKS / "guardrail_core.py"
    spec = importlib.util.spec_from_file_location("guardrail_core", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    if str(CORE_HOOKS) not in sys.path:
        sys.path.insert(0, str(CORE_HOOKS))
    sys.modules["guardrail_core"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def guardrail_core():
    return _load_guardrail_core()


def test_rules_script_outside_plugin_root_is_rejected(
    guardrail_core, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    outside = tmp_path / "outside-rules.py"
    outside.write_text("import json\nprint(json.dumps({'ok': True, 'rules': []}))\n", encoding="utf-8")

    monkeypatch.setenv("SW_RULES_SCRIPT", str(outside))
    assert guardrail_core._resolve_rules_script_override(plugin) is None
    ok, rules, failure_code = guardrail_core.fetch_rules(workspace, plugin, {"memory": {}})
    assert ok is False
    assert rules == []
    assert failure_code is None


def test_adapter_receives_no_credential_without_resolution(
    guardrail_core, tmp_path: Path
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    plugin = tmp_path / "plugin"
    plugin.mkdir()

    parent = {
        "PATH": "/usr/bin",
        "GITHUB_TOKEN": "inherited-token",
        "RECALLIUM_API_KEY": "inherited-recallium",
    }
    config = {
        "memory": {
            "credentialRef": "memory-main",
            "tokenEnv": "RECALLIUM_API_KEY",
        }
    }
    env = guardrail_core.build_adapter_spawn_env(workspace, plugin, config, parent=parent)
    assert "GITHUB_TOKEN" not in env
    assert "RECALLIUM_API_KEY" not in env


def test_adapter_receives_only_resolved_credential(
    guardrail_core, tmp_path: Path
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    plugin = tmp_path / "plugin"
    plugin.mkdir()

    parent = {
        "PATH": "/usr/bin",
        "GITHUB_TOKEN": "inherited-token",
        "RECALLIUM_API_KEY": "inherited-recallium",
    }
    config = {
        "memory": {
            "credentialRef": "memory-main",
            "tokenEnv": "RECALLIUM_API_KEY",
        }
    }
    resolved = Resolution.resolved(
        CredentialRef("memory-main"),
        ResolvedToken(Secret("broker-recallium-token")),
    )
    with patch("credentials.resolver.resolve", return_value=resolved):
        env = guardrail_core.build_adapter_spawn_env(workspace, plugin, config, parent=parent)

    assert env.get("RECALLIUM_API_KEY") == "broker-recallium-token"
    assert "GITHUB_TOKEN" not in env
    credential_keys = [key for key in env if key.endswith("TOKEN") or key.endswith("_KEY")]
    assert credential_keys == ["RECALLIUM_API_KEY"]


def test_unresolved_reference_does_not_inject_credential(
    guardrail_core, tmp_path: Path,
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    plugin = tmp_path / "plugin"
    plugin.mkdir()

    config = {
        "memory": {
            "credentialRef": "memory-main",
            "tokenEnv": "RECALLIUM_API_KEY",
        }
    }
    unresolved = Resolution.unresolved(CredentialRef("memory-main"), reason="missing-selector")
    assert unresolved.state is ResolutionState.UNRESOLVED
    with patch("credentials.resolver.resolve", return_value=unresolved):
        env = guardrail_core.build_adapter_spawn_env(
            workspace,
            plugin,
            config,
            parent={"RECALLIUM_API_KEY": "inherited"},
        )
    assert "RECALLIUM_API_KEY" not in env
