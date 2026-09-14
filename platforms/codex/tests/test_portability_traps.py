"""Codex portability trap tests (PRD 349 R24/R25 / TS5)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_CODEX = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    if str(_CODEX) not in sys.path:
        sys.path.insert(0, str(_CODEX))
    if str(_REPO / "scripts") not in sys.path:
        sys.path.insert(0, str(_REPO / "scripts"))
    spec.loader.exec_module(mod)
    return mod


_hook = _load("codex_hook_registry", _CODEX / "hook_registry.py")
_manifest = _load("codex_plugin_manifest", _CODEX / "plugin_manifest.py")
_gen = _load("codex_generator", _CODEX / "generator.py")


def test_r24_cli_and_desktop_are_separate_capability_entries() -> None:
    raw = json.loads((_REPO / "core/schemas/capabilities/codex.json").read_text(encoding="utf-8"))
    assert isinstance(raw, list)
    surfaces = {row["surface"]: row for row in raw}
    assert "cli" in surfaces and "desktop" in surfaces
    assert surfaces["cli"]["surface"] != surfaces["desktop"]["surface"]
    for unsupported_surface in ("ide", "cloud"):
        assert (
            surfaces[unsupported_surface]["capabilities"]["emit_hook"]["implementation_mode"]
            == "unsupported"
        )


def test_r25_tool_permission_pre_approval_vs_claude_allowed_tools() -> None:
    contract = _hook.portability_trap_contract()
    assert contract["tool_permission_mode"] == "pre_approval"
    assert _hook.TOOL_PERMISSION_MODE == "pre_approval"
    assert contract["claude_contrast"] == "allowed-tools"


def test_r25_positional_arg_starts_at_one() -> None:
    contract = _hook.portability_trap_contract()
    assert contract["positional_arg_start_index"] == 1
    assert _hook.POSITIONAL_ARG_START_INDEX == 1


def test_r25_instruction_discovery_via_adapter_path_not_env() -> None:
    contract = _hook.portability_trap_contract()
    assert contract["instruction_discovery"] == "adapter_resolved_path"
    assert contract["forbidden_instruction_env_vars"]


def test_r22_handlers_cover_supported_events_only() -> None:
    handlers = _hook.registered_handlers("codex")
    host_events = {h["host_event"] for h in handlers}
    assert "session.start" in host_events
    assert handlers
    assert all(h["canonical"] not in {"Notification", "ContextSwitch"} for h in handlers)


def test_r20_r21_generator_manifest_and_no_skill_body_duplication(tmp_path: Path) -> None:
    out = _gen.generate(tmp_path / "codex", repo_root=_REPO, core_root=_REPO / "core")
    manifest = json.loads((out / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert _manifest.validate_codex_plugin_manifest(manifest) == []
    assert manifest["skills"] == "./skills/"
    assert (out / "skills" / "sw-init" / "SKILL.md").is_file()
    assert (out / "hooks" / "hooks.json").is_file()
    native_hooks = json.loads((out / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    assert "SessionStart" in native_hooks["hooks"]
    index = json.loads((out / "skills" / "index.json").read_text(encoding="utf-8"))
    skill_ids = [s["id"] for s in index["skills"]]
    assert list(out.rglob("SKILL.md")), "PRD 352 R4 requires shipped skill bodies"
    out2 = _gen.generate(tmp_path / "codex2", repo_root=_REPO, core_root=_REPO / "core")
    index2 = json.loads((out2 / "skills" / "index.json").read_text(encoding="utf-8"))
    assert skill_ids == [s["id"] for s in index2["skills"]]
    assert [c["id"] for c in index["commands"]] == [c["id"] for c in index2["commands"]]


def test_r23_mcp_config_uses_shipwright_paths(tmp_path: Path) -> None:
    out = _gen.generate(
        tmp_path / "codex", repo_root=_REPO, core_root=_REPO / "core", enable_mcp=True
    )
    mcp = json.loads((out / "mcp" / "shipwright.json").read_text(encoding="utf-8"))
    assert mcp["adapter_id"] == "codex"
    assert "codex" in mcp["config_path"]
    assert "/.codex/" not in mcp["config_path"]


def test_generator_emits_closed_sw_reference(tmp_path: Path) -> None:
    out = _gen.generate(tmp_path / "codex", repo_root=_REPO, core_root=_REPO / "core")
    assert (out / "core" / "sw-reference" / "config.schema.json").is_file()
    assert (out / "core" / "sw-reference" / "memory-provider-catalog.json").is_file()
    assert (out / "core" / "sw-reference" / "templates" / "ci-stub-pull-request.yml").is_file()
