"""Pytest port of run_guardrail_rules_resolution_fixtures.py (PRD 054 W1 behavioral).

Also covers PRD 084 R5 — scope-refusal codes bypass provider_unreachable_message.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

_PKG = "scripts/unit_tests/guardrails"
_HARNESS = "harness_guardrail_rules_resolution.py"
CORE_HOOKS = Path(__file__).resolve().parents[3] / "core" / "hooks"


def _load_harness(repo_root: Path):
    path = repo_root / _PKG / _HARNESS
    for entry in (str(repo_root / "scripts" / "test"), str(repo_root / "scripts")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    spec = importlib.util.spec_from_file_location("harness_guardrail_rules_resolution", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load harness {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_guardrail_core():
    path = CORE_HOOKS / "guardrail_core.py"
    spec = importlib.util.spec_from_file_location("guardrail_core", path)
    assert spec and spec.loader, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    if str(CORE_HOOKS) not in sys.path:
        sys.path.insert(0, str(CORE_HOOKS))
    sys.modules["guardrail_core"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def guardrail_core():
    return _load_guardrail_core()


def _write_enforce_config(workspace: Path, provider: str = "recallium") -> None:
    cursor = workspace / ".cursor"
    cursor.mkdir(parents=True, exist_ok=True)
    (cursor / "workflow.config.json").write_text(
        json.dumps(
            {
                "memory": {
                    "provider": provider,
                    "project": "scope-refusal-test",
                    "guardrails": {"enforceBeforeSubmit": True},
                }
            }
        ),
        encoding="utf-8",
    )


def _plugin_with_rules_script(tmp_path: Path) -> Path:
    plugin = tmp_path / "plugin"
    providers = plugin / "providers"
    providers.mkdir(parents=True)
    # Script body is unused when subprocess.run is stubbed; path must exist + be allowed.
    (providers / "recallium-rules.py").write_text(
        "import json\nprint(json.dumps({'ok': True, 'rules': []}))\n",
        encoding="utf-8",
    )
    return plugin


def test_guardrail_rules_resolution_behavior(repo_root: Path, sw_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in sw_env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.chdir(repo_root)
    mod = _load_harness(repo_root)
    assert int(mod.main()) == 0


def test_guardrail_rules_resolution_harness_present(repo_root: Path) -> None:
    """R16 — harness module must exist (fail-closed if port regresses)."""
    assert (repo_root / _PKG / _HARNESS).is_file()


def test_scope_refusal_code_bypasses_provider_unreachable_message(
    guardrail_core, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R5 — broker scope refusal code must not surface as provider-unreachable."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _write_enforce_config(workspace)
    plugin = _plugin_with_rules_script(tmp_path)
    script = plugin / "providers" / "recallium-rules.py"
    monkeypatch.setenv("SW_RULES_SCRIPT", str(script))

    payload = {
        "ok": False,
        "code": "resolver-provider-mismatch",
        "error": "provider mismatch for memory credential ref",
        "rules": [],
    }
    stub = SimpleNamespace(returncode=1, stdout=json.dumps(payload), stderr="")

    with patch.object(guardrail_core.subprocess, "run", return_value=stub):
        result = guardrail_core.evaluate_submit_guard(workspace, plugin)

    unreachable = guardrail_core.provider_unreachable_message("recallium")
    assert result.allow is False
    assert result.message != unreachable
    assert "resolver-provider-mismatch" in result.message
    assert "credential scope refusal" in result.message
    assert "cannot reach Recallium" not in result.message


def test_genuine_unreachability_keeps_provider_unreachable_message(
    guardrail_core, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R5 companion — timeout / code-absent failure still uses unreachable text."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _write_enforce_config(workspace)
    plugin = _plugin_with_rules_script(tmp_path)
    script = plugin / "providers" / "recallium-rules.py"
    monkeypatch.setenv("SW_RULES_SCRIPT", str(script))
    # Stub plugin has no catalog; pin provider so unreachable text is deterministic.
    monkeypatch.setattr(
        guardrail_core,
        "resolve_memory_provider",
        lambda *args, **kwargs: "recallium",
    )

    unreachable = guardrail_core.provider_unreachable_message("recallium")

    with patch.object(
        guardrail_core.subprocess,
        "run",
        side_effect=subprocess.TimeoutExpired(cmd=["python"], timeout=5),
    ):
        timed_out = guardrail_core.evaluate_submit_guard(workspace, plugin)
    assert timed_out.allow is False
    assert timed_out.message == unreachable

    # Non-zero exit with ok:false but no code field → still unreachable messaging.
    no_code = SimpleNamespace(
        returncode=1,
        stdout=json.dumps({"ok": False, "error": "provider unreachable", "rules": []}),
        stderr="",
    )
    with patch.object(guardrail_core.subprocess, "run", return_value=no_code):
        without_code = guardrail_core.evaluate_submit_guard(workspace, plugin)
    assert without_code.allow is False
    assert without_code.message == unreachable
