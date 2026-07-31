"""Hook child-environment adoption tests (PRD 080 11.3 / R5)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

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


def _env_probe_script() -> str:
    return (
        "import json, os, sys\n"
        "print(json.dumps({k: os.environ.get(k) for k in sys.argv[1:]}))\n"
    )


def test_empty_parent_yields_platform_only_context(
    guardrail_core, repo_root: Path, tmp_path: Path
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    plugin = tmp_path / "plugin"
    providers = plugin / "providers"
    providers.mkdir(parents=True)
    script = providers / "probe-rules.py"
    script.write_text(_env_probe_script(), encoding="utf-8")

    parent = {"PATH": "/usr/bin", "GITHUB_TOKEN": "inherited-token"}
    env = guardrail_core.build_adapter_spawn_env(
        workspace,
        plugin,
        {"memory": {}},
        parent=parent,
    )
    assert "GITHUB_TOKEN" not in env
    assert env.get("PATH") == "/usr/bin"
    assert env.get("SW_WORKSPACE_ROOT") == str(workspace)


def test_one_declared_context_key_survives(
    guardrail_core, repo_root: Path, tmp_path: Path
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    plugin = tmp_path / "plugin"
    providers = plugin / "providers"
    providers.mkdir(parents=True)
    script = providers / "probe-rules.py"
    script.write_text(_env_probe_script(), encoding="utf-8")

    parent = {
        "PATH": "/usr/bin",
        "SW_WORKSPACE_ROOT": "ignored-parent-value",
        "SW_RUN_DIR": ".cursor/sw-deliver-runs/example",
        "GITHUB_TOKEN": "inherited-token",
    }
    env = guardrail_core.build_adapter_spawn_env(
        workspace,
        plugin,
        {"memory": {}},
        parent=parent,
    )
    assert env["SW_WORKSPACE_ROOT"] == str(workspace)
    assert "SW_RUN_DIR" not in env
    assert "GITHUB_TOKEN" not in env


def test_fetch_rules_child_sees_only_allowlisted_keys(
    guardrail_core, repo_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    plugin = tmp_path / "plugin"
    providers = plugin / "providers"
    providers.mkdir(parents=True)
    script = providers / "probe-rules.py"
    script.write_text(
        "import json, os\n"
        "payload = {\n"
        "  'ok': True,\n"
        "  'rules': [],\n"
        "  'env': {k: os.environ.get(k) for k in sorted(os.environ)}\n"
        "}\n"
        "print(json.dumps(payload))\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SW_RULES_SCRIPT", str(script))
    monkeypatch.setenv("GITHUB_TOKEN", "inherited-token")
    monkeypatch.setenv("SW_RUN_DIR", ".cursor/sw-deliver-runs/example")

    ok, rules, failure_code = guardrail_core.fetch_rules(
        workspace,
        plugin,
        {"memory": {}},
        rules_script=script,
    )
    assert ok is True
    assert rules == []
    assert failure_code is None
