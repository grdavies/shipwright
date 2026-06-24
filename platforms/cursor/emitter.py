"""Cursor platform emitter — produces dist/cursor/ (expanded in U6)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from emitter_base import EmitterBase, EmitterError, ensure_clean_dir

SUPPORTED = {
    "hooks": {"native"},
    "skills": {"native"},
    "commands": {"slash-md"},
    "rules": {"mdc"},
    "subagents": {"native"},
    "mcp": {"yes"},
    "memoryXport": {"mcp"},
}


class CursorEmitter(EmitterBase):
    def validate_descriptor(self) -> None:
        for key, allowed in SUPPORTED.items():
            value = self.descriptor.get(key)
            if value not in allowed:
                raise EmitterError(
                    f"cursor emitter cannot satisfy capability {key}={value!r} "
                    f"(allowed: {sorted(allowed)})"
                )

    def plugin_root_env_name(self) -> str:
        return "CURSOR_PLUGIN_ROOT"

    def emit(self, core_root: Path, repo_root: Path, dest: Path) -> None:
        self.validate_descriptor()
        ensure_clean_dir(dest)
        self.copy_emittable_content(core_root, dest)
        self._copy_runtime_support(core_root, repo_root, dest)
        self._emit_plugin_manifest(dest)
        self._emit_hooks(repo_root, dest)

    def _copy_runtime_support(self, core_root: Path, repo_root: Path, dest: Path) -> None:
        """Copy shared hook runtime so emitted tree is self-contained."""
        hooks_src = core_root / "hooks"
        if hooks_src.is_dir():
            shutil.copytree(hooks_src, dest / "core" / "hooks")
        adapter_src = repo_root / "platforms" / "cursor" / "hook_adapter.py"
        if adapter_src.is_file():
            plat_dir = dest / "platforms" / "cursor"
            plat_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(adapter_src, plat_dir / "hook_adapter.py")

    def _emit_plugin_manifest(self, dest: Path) -> None:
        manifest_dir = dest / ".cursor-plugin"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        plugin = {
            "name": "phase-flow-v2",
            "version": "0.1.0",
            "description": "phase-flow v2 (generated)",
            "commands": "./commands/",
            "skills": "./skills/",
            "agents": "./agents/",
            "rules": "./rules/",
            "hooks": "./hooks/hooks.json",
        }
        (manifest_dir / "plugin.json").write_text(
            json.dumps(plugin, indent=2) + "\n",
            encoding="utf-8",
        )

    def _emit_hooks(self, repo_root: Path, dest: Path) -> None:
        hooks_dir = dest / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        for name in (
            "session-start.py",
            "before-submit-guardrails.py",
            "memory-sync-stop.py",
            "session-context.md",
        ):
            src = repo_root / "hooks" / name
            if src.is_file():
                shutil.copy2(src, hooks_dir / name)
        hooks_json = {
            "version": 1,
            "hooks": {
                "sessionStart": [
                    {"command": 'python3 "${CURSOR_PLUGIN_ROOT}/hooks/session-start.py"'}
                ],
                "beforeSubmitPrompt": [
                    {"command": 'python3 "${CURSOR_PLUGIN_ROOT}/hooks/before-submit-guardrails.py"'}
                ],
                "stop": [
                    {"command": 'python3 "${CURSOR_PLUGIN_ROOT}/hooks/memory-sync-stop.py"'}
                ],
            },
        }
        (hooks_dir / "hooks.json").write_text(
            json.dumps(hooks_json, indent=2) + "\n",
            encoding="utf-8",
        )


def emit(core_root: Path, repo_root: Path, dest: Path) -> None:
    descriptor_path = repo_root / "platforms" / "cursor" / "descriptor.json"
    descriptor = EmitterBase.load_descriptor(descriptor_path)
    CursorEmitter(descriptor).emit(core_root, repo_root, dest)
