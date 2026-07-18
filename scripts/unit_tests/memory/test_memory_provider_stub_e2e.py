"""PRD 071 R6/R12 — hermetic third-provider fixture end-to-end integration."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import memory_sot as ms
import memory_switch as msw
import wave_memory_prework as prework
from memory_provider_catalog import load_catalog
from memory_provider_register import RegistrationError, validate_registration

FIXTURE = SCRIPTS / "test/fixtures/memory-provider-stub"
STUB_PROVIDER_ID = "memory-stub"
CORE_HOOKS = SCRIPTS.parent / "core" / "hooks"

_SCRIPTS_TO_COPY = (
    "scripts/memory_provider_catalog.py",
    "scripts/memory_provider_register.py",
    "scripts/capability_index.py",
    "scripts/sw_resolve_plugin_root.py",
    "scripts/memory_adapter_checklist.py",
    "scripts/sw_recallium_url.py",
)


def _load_hook_module(name: str):
    path = CORE_HOOKS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    if str(CORE_HOOKS) not in sys.path:
        sys.path.insert(0, str(CORE_HOOKS))
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _install_stub_workspace(workspace: Path, repo_root: Path) -> None:
    """Materialize catalog row + adapter + rules under an isolated workspace."""
    catalog = json.loads(json.dumps(load_catalog(repo_root)))
    row = json.loads((FIXTURE / "catalog-row.json").read_text(encoding="utf-8"))
    catalog["providers"][STUB_PROVIDER_ID] = row

    catalog_path = workspace / ".sw" / "memory-provider-catalog.json"
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

    for rel in _SCRIPTS_TO_COPY:
        src = repo_root / rel
        dest = workspace / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    for name in ("adapter.md", "stub-rules.py", "catalog-row.json", "config-stub.json"):
        src = FIXTURE / name
        dest = workspace / "scripts/test/fixtures/memory-provider-stub" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    cursor = workspace / ".cursor"
    cursor.mkdir(parents=True, exist_ok=True)
    config = json.loads((FIXTURE / "config-stub.json").read_text(encoding="utf-8"))
    (cursor / "workflow.config.json").write_text(json.dumps(config), encoding="utf-8")


@pytest.fixture(scope="module")
def sw_hook_util():
    return _load_hook_module("sw_hook_util")


@pytest.fixture(scope="module")
def guardrail_core():
    return _load_hook_module("guardrail_core")


def test_stub_registration_passes_config_validation(repo_root: Path, tmp_path: Path) -> None:
    """O — catalog row + adapter + rules register without enum or command edits."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _install_stub_workspace(workspace, repo_root)

    result = validate_registration(workspace, STUB_PROVIDER_ID)
    assert result["providerId"] == STUB_PROVIDER_ID
    assert result["adapterDoc"] == "scripts/test/fixtures/memory-provider-stub/adapter.md"
    assert result["rulesScript"] == "scripts/test/fixtures/memory-provider-stub/stub-rules.py"


def test_stub_rules_script_resolves_for_hook_fetch(
    repo_root: Path, tmp_path: Path, sw_hook_util
) -> None:
    """O — hook layer resolves the stub rules script from catalog metadata."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _install_stub_workspace(workspace, repo_root)

    plugin_root = workspace
    resolved = sw_hook_util.rules_script_for_provider(plugin_root, STUB_PROVIDER_ID)
    assert resolved is not None
    assert resolved.name == "stub-rules.py"
    assert resolved.is_file()

    proc = subprocess.run(
        [sys.executable, str(resolved)],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["rules"] == []


def test_stub_empty_reachable_rules_allow_submit(
    repo_root: Path, tmp_path: Path, guardrail_core, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M — reachable empty rules are non-blocking for submit guard."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _install_stub_workspace(workspace, repo_root)

    monkeypatch.delenv("SW_RULES_SCRIPT", raising=False)
    result = guardrail_core.evaluate_submit_guard(workspace, workspace)
    assert result.allow is True


def test_stub_prework_reachability_is_registration_gated(
    repo_root: Path, tmp_path: Path
) -> None:
    """O — MCP transport reachability follows validate_registration, not recallium-only."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _install_stub_workspace(workspace, repo_root)
    config = json.loads((workspace / ".cursor/workflow.config.json").read_text(encoding="utf-8"))

    assert prework.probe_provider_reachable(workspace, STUB_PROVIDER_ID, config) is True


def test_stub_auto_sot_reads_catalog_memory_authoritative(
    repo_root: Path, tmp_path: Path
) -> None:
    """O — auto SoT follows catalog sourceOfTruthClass for the stub provider."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _install_stub_workspace(workspace, repo_root)

    provider = ms.resolve_memory_provider(workspace)
    assert provider == STUB_PROVIDER_ID
    assert ms.resolve_effective_sot("auto", provider, "decision", root=workspace) == "memory"


def test_stub_switch_flow_skip_ack_dry_path(repo_root: Path, tmp_path: Path) -> None:
    """I — unsupported interchange routes to skip-ack; dry acknowledgement passes."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _install_stub_workspace(workspace, repo_root)
    catalog = load_catalog(workspace)

    plan = msw.plan_switch(catalog, STUB_PROVIDER_ID, "in-repo", fmt="jsonl")
    assert plan["path"] == "skip"
    assert plan["migration"] == "blocked"

    halted = msw.skip_ack_step(workspace, STUB_PROVIDER_ID, "in-repo", acknowledged=False)
    assert halted["verdict"] == "halt"
    assert halted["requiresAcknowledgement"] is True

    done = msw.skip_ack_step(workspace, STUB_PROVIDER_ID, "in-repo", acknowledged=True)
    assert done["verdict"] == "pass"
    assert done["switch"]["next"] == "in-repo"


def test_stub_unknown_catalog_row_fails_registration(repo_root: Path, tmp_path: Path) -> None:
    """E — provider id absent from catalog fails closed."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _install_stub_workspace(workspace, repo_root)

    with pytest.raises(RegistrationError) as exc:
        validate_registration(workspace, "not-registered")
    assert exc.value.cause == "unknown"
