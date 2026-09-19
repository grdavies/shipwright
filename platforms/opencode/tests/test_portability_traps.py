"""OpenCode portability trap tests (PRD 349 R28/R29 / TS5)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

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


def test_r1_restore_plan_emit_has_no_worktree_paths(tmp_path: Path) -> None:
    out = _gen.generate(tmp_path / "opencode", repo_root=_REPO, core_root=_REPO / "core")
    mcp = json.loads((out / "mcp" / "shipwright.json").read_text(encoding="utf-8"))
    blob = json.dumps(mcp)
    assert ".sw-worktrees/" not in blob


def test_r4_terminal_prepare_fail_closed_on_orch_mcp_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    import pytest

    scripts = str(_REPO / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import mcp_path_predicate

    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    bad_rel = "dist/opencode/mcp/shipwright.json"
    bad_path = root / bad_rel
    bad_path.parent.mkdir(parents=True)
    bad_path.write_text(
        json.dumps(
            {
                "adapter_id": "opencode",
                "config_path": str(root / ".sw-worktrees" / "orch" / ".shipwright" / "mcp" / "opencode.json"),
                "mcpServers": {
                    "shipwright-bounded": {
                        "command": "python3",
                        "args": [str(root / ".sw-worktrees" / "orch" / "core" / "mcp" / "server.py")],
                        "transport": "stdio",
                    }
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="terminal-prepare"):
        mcp_path_predicate.assert_terminal_prepare_mcp_paths(root)

    bad_path.unlink()
    primary = root / "primary-abs"
    primary.mkdir()
    monkeypatch.setattr(mcp_path_predicate, "primary_checkout_root", lambda _start=None: primary.resolve())
    good_path = root / "dist/codex/mcp/shipwright.json"
    good_path.parent.mkdir(parents=True, exist_ok=True)
    good_path.write_text(
        json.dumps(
            {
                "adapter_id": "codex",
                "config_path": str(primary / ".shipwright" / "mcp" / "codex.json"),
                "mcpServers": {
                    "shipwright-bounded": {
                        "command": "python3",
                        "args": [str(primary / "core" / "mcp" / "server.py")],
                        "transport": "stdio",
                    }
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    mcp_path_predicate.assert_terminal_prepare_mcp_paths(root)
