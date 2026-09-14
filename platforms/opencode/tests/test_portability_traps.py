"""OpenCode portability trap tests (PRD 349 R28/R29 / TS5)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_OC = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    # Avoid colliding with similarly named modules from other adapters.
    sys.modules.pop(name, None)
    for key in list(sys.modules):
        if key in {"hook_registry", "generator", "plugin_manifest"}:
            sys.modules.pop(key, None)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    # Prefer this adapter dir for sibling imports.
    sys.path = [str(_OC), str(_REPO / "scripts"), *[p for p in sys.path if p not in {str(_OC)}]]
    spec.loader.exec_module(mod)
    return mod


_hook = _load("opencode_hook_registry", _OC / "hook_registry.py")
_gen = _load("opencode_generator", _OC / "generator.py")


def test_r26_distinct_package_mechanism(tmp_path: Path) -> None:
    out = _gen.generate(tmp_path / "opencode", repo_root=_REPO, core_root=_REPO / "core")
    assert (out / "opencode.plugin.json").is_file()
    assert not (out / ".claude-plugin").exists()
    assert not (out / "CLAUDE.md").exists()
    pkg = json.loads((out / "opencode.plugin.json").read_text(encoding="utf-8"))
    assert pkg["package_mechanism"] == "opencode-plugin"


def test_r27_lifecycle_plugin_is_thin_shim(tmp_path: Path) -> None:
    out = _gen.generate(tmp_path / "opencode", repo_root=_REPO, core_root=_REPO / "core")
    shim = (out / "lifecycle_plugin.ts").read_text(encoding="utf-8")
    assert "registerLifecycleHooks" in shim
    assert "dispatchLifecycleStdin" in shim
    assert list(out.rglob("SKILL.md")), "PRD 352 R4 requires shipped skill bodies"


def test_r28_handlers_and_unsupported_diagnostics() -> None:
    handlers = _hook.registered_handlers("opencode")
    assert handlers
    assert all(h["canonical"] not in {"Notification", "ContextSwitch"} for h in handlers)
    diags = _hook.lifecycle_plugin_unsupported_diagnostics()
    assert diags
    assert all(d.get("code") == "unsupported_event" for d in diags)


def test_r29_tool_permissions_require_explicit_confirmation() -> None:
    contract = _hook.portability_trap_contract()
    assert contract["tool_permission_mode"] == "explicit_user_confirmation"
    assert _hook.TOOL_PERMISSION_MODE == "explicit_user_confirmation"


def test_r29_positional_indexing() -> None:
    assert _hook.portability_trap_contract()["positional_arg_start_index"] == 1
    assert _hook.POSITIONAL_ARG_START_INDEX == 1


def test_r29_instruction_discovery_adapter_resolved() -> None:
    contract = _hook.portability_trap_contract()
    assert contract["instruction_discovery"] == "adapter_resolved_path"
    assert contract["forbidden_instruction_env_vars"]


def test_r30_mcp_config_no_conflict_with_codex(tmp_path: Path) -> None:
    codex_dir = _REPO / "platforms" / "codex"
    # Load codex generator with its own dir preferred.
    sys.modules.pop("codex_generator_for_oc_test", None)
    for key in list(sys.modules):
        if key in {"hook_registry", "generator", "plugin_manifest"}:
            sys.modules.pop(key, None)
    sys.path = [str(codex_dir), str(_REPO / "scripts"), *[p for p in sys.path if p != str(codex_dir)]]
    spec = importlib.util.spec_from_file_location(
        "codex_generator_for_oc_test", codex_dir / "generator.py"
    )
    assert spec and spec.loader
    codex_gen = importlib.util.module_from_spec(spec)
    sys.modules["codex_generator_for_oc_test"] = codex_gen
    spec.loader.exec_module(codex_gen)

    oc = _gen.generate(tmp_path / "opencode", repo_root=_REPO, core_root=_REPO / "core")
    cx = codex_gen.generate(tmp_path / "codex", repo_root=_REPO, core_root=_REPO / "core")
    oc_mcp = json.loads((oc / "mcp" / "shipwright.json").read_text(encoding="utf-8"))
    cx_mcp = json.loads((cx / "mcp" / "shipwright.json").read_text(encoding="utf-8"))
    assert oc_mcp["config_path"] != cx_mcp["config_path"]
    assert oc_mcp["adapter_id"] == "opencode"
    assert cx_mcp["adapter_id"] == "codex"
    assert "/.opencode/" not in oc_mcp["config_path"]
