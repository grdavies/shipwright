"""PRD 071 R4 — fail-closed hook trust wiring regression tests."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

CORE_HOOKS = Path(__file__).resolve().parents[3] / "core" / "hooks"


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


@pytest.fixture(scope="module")
def sw_hook_util():
    return _load_hook_module("sw_hook_util")


@pytest.fixture(scope="module")
def guardrail_core():
    return _load_hook_module("guardrail_core")


@pytest.fixture
def plugin_root(repo_root: Path) -> Path:
    return repo_root


def _write_config(workspace: Path, provider: str, **guardrails: object) -> None:
    cursor = workspace / ".cursor"
    cursor.mkdir(parents=True, exist_ok=True)
    payload = {
        "memory": {
            "provider": provider,
            "project": "hook-test",
            "guardrails": {"enforceBeforeSubmit": True, **guardrails},
        }
    }
    (cursor / "workflow.config.json").write_text(json.dumps(payload), encoding="utf-8")


def _clone_plugin_root(repo_root: Path, tmp_path: Path) -> Path:
    """Minimal plugin tree with catalog + adapters for isolated rule-script tests."""
    plugin = tmp_path / "plugin"
    for rel in (
        ".sw/memory-provider-catalog.json",
        "core/providers/recallium.md",
        "core/providers/in-repo.md",
        "scripts/memory_provider_catalog.py",
        "scripts/memory_provider_register.py",
        "scripts/capability_index.py",
        "scripts/sw_resolve_plugin_root.py",
    ):
        src = repo_root / rel
        dest = plugin / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    providers = plugin / "providers"
    providers.mkdir(parents=True, exist_ok=True)
    for name in ("recallium-rules.py", "in-repo-rules.py"):
        src = repo_root / "providers" / name
        if src.is_file():
            (providers / name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return plugin


@pytest.mark.parametrize("provider_id", ["recallium", "in-repo"])
def test_rules_script_resolves_catalog_path(
    repo_root: Path, plugin_root: Path, sw_hook_util, provider_id: str
) -> None:
    resolved = sw_hook_util.rules_script_for_provider(plugin_root, provider_id)
    assert resolved is not None
    assert resolved.suffix == ".py"
    assert resolved.is_file()


def test_unknown_provider_blocked(repo_root: Path, plugin_root: Path, sw_hook_util) -> None:
    assert (
        sw_hook_util.resolve_memory_provider(
            repo_root,
            {"memory": {"provider": "not-a-real-provider"}},
            plugin_root=plugin_root,
        )
        is None
    )
    assert sw_hook_util.rules_script_for_provider(plugin_root, "not-a-real-provider") is None


def test_unreachable_rules_script_blocks_submit(
    repo_root: Path, guardrail_core, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "ws"
    plugin = _clone_plugin_root(repo_root, tmp_path)
    _write_config(workspace, "recallium")

    broken = plugin / "providers" / "recallium-rules.py"
    broken.write_text("raise RuntimeError(\"unreachable\")\n", encoding="utf-8")

    monkeypatch.delenv("SW_RULES_SCRIPT", raising=False)
    result = guardrail_core.evaluate_submit_guard(workspace, plugin)
    assert result.allow is False
    assert "cannot reach Recallium" in result.message or "cannot load rule-class guardrails" in result.message


def test_empty_reachable_rules_allow_submit(
    repo_root: Path, guardrail_core, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "ws"
    plugin = _clone_plugin_root(repo_root, tmp_path)
    _write_config(workspace, "in-repo")

    empty_rules = plugin / "providers" / "in-repo-rules.py"
    empty_rules.write_text(
        "import json\nprint(json.dumps({'ok': True, 'rules': []}))\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("SW_RULES_SCRIPT", raising=False)
    result = guardrail_core.evaluate_submit_guard(workspace, plugin)
    assert result.allow is True


def test_plugin_layout_emit_catalog_allows_submit(
    repo_root: Path, guardrail_core, sw_hook_util, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Installed plugin has emit under core/sw-reference but no .sw/ catalog."""
    workspace = tmp_path / "ws"
    plugin = _clone_plugin_root(repo_root, tmp_path)
    sw_catalog = plugin / ".sw" / "memory-provider-catalog.json"
    emit = plugin / "core" / "sw-reference" / "memory-provider-catalog.json"
    emit.parent.mkdir(parents=True, exist_ok=True)
    emit.write_text(sw_catalog.read_text(encoding="utf-8"), encoding="utf-8")
    sw_catalog.unlink()
    (plugin / ".sw").rmdir()
    _write_config(workspace, "in-repo")
    empty_rules = plugin / "providers" / "in-repo-rules.py"
    empty_rules.write_text(
        "import json\nprint(json.dumps({'ok': True, 'rules': []}))\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("SW_RULES_SCRIPT", raising=False)
    assert sw_hook_util.validate_hook_provider(plugin, "in-repo") is True
    result = guardrail_core.evaluate_submit_guard(workspace, plugin)
    assert result.allow is True


def test_no_cross_provider_rule_fetcher_swap(
    repo_root: Path, guardrail_core, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "ws"
    plugin = _clone_plugin_root(repo_root, tmp_path)
    _write_config(workspace, "in-repo")

    (plugin / "providers" / "recallium-rules.py").write_text(
        "import json\nprint(json.dumps({'ok': True, 'rules': [{'id': 'x', 'summary': 'recallium-only'}]}))\n",
        encoding="utf-8",
    )
    (plugin / "providers" / "in-repo-rules.py").write_text(
        "import json\nprint(json.dumps({'ok': True, 'rules': []}))\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("SW_RULES_SCRIPT", raising=False)
    summaries = guardrail_core.fetch_rule_summaries(workspace, plugin, guardrail_core.load_config(workspace))
    assert summaries == []
