"""Claude Code platform emitter — produces dist/claude-code/ (expanded in U7)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from emitter_base import EmitterBase, EmitterError, ensure_clean_dir

SUPPORTED = {
    "hooks": {"native"},
    "skills": {"native"},
    "commands": {"slash-md"},
    "rules": {"claude-md"},
    "subagents": {"native"},
    "mcp": {"yes"},
    "memoryXport": {"mcp"},
}


class ClaudeCodeEmitter(EmitterBase):
    def validate_descriptor(self) -> None:
        for key, allowed in SUPPORTED.items():
            value = self.descriptor.get(key)
            if value not in allowed:
                raise EmitterError(
                    f"claude-code emitter cannot satisfy capability {key}={value!r} "
                    f"(allowed: {sorted(allowed)})"
                )

    def plugin_root_env_name(self) -> str:
        return "CLAUDE_PLUGIN_ROOT"

    def emit(self, core_root: Path, repo_root: Path, dest: Path) -> None:
        self.validate_descriptor()
        ensure_clean_dir(dest)
        self.copy_emittable_content(core_root, dest)
        self._copy_runtime_support(core_root, repo_root, dest)
        self._emit_plugin_manifest(dest)
        self._emit_hooks(repo_root, dest)
        self._emit_claude_md(core_root, dest)

    def _copy_runtime_support(self, core_root: Path, repo_root: Path, dest: Path) -> None:
        hooks_src = core_root / "hooks"
        if hooks_src.is_dir():
            shutil.copytree(hooks_src, dest / "core" / "hooks")
        adapter_src = repo_root / "platforms" / "claude-code" / "hook_adapter.py"
        if adapter_src.is_file():
            plat_dir = dest / "platforms" / "claude-code"
            plat_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(adapter_src, plat_dir / "hook_adapter.py")

    def _emit_plugin_manifest(self, dest: Path) -> None:
        manifest_dir = dest / ".claude-plugin"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        plugin = {
            "name": "phase-flow-v2",
            "version": "0.1.0",
            "description": "phase-flow v2 for Claude Code (generated)",
        }
        (manifest_dir / "plugin.json").write_text(
            json.dumps(plugin, indent=2) + "\n",
            encoding="utf-8",
        )

    def _emit_hooks(self, repo_root: Path, dest: Path) -> None:
        adapter_src = repo_root / "platforms" / "claude-code" / "hook_adapter.py"
        hooks_dir = dest / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        if adapter_src.is_file():
            shutil.copy2(adapter_src, hooks_dir / "hook_adapter.py")
        wrapper = '''#!/usr/bin/env python3
import sys
from pathlib import Path
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "core" / "hooks"))
sys.path.insert(0, str(_REPO / "platforms" / "claude-code"))
import hook_adapter
if __name__ == "__main__":
    raise SystemExit(hook_adapter.dispatch(_REPO))
'''
        (hooks_dir / "claude-hook.py").write_text(wrapper, encoding="utf-8")
        hooks_json = {
            "hooks": {
                "SessionStart": [
                    {"command": 'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/claude-hook.py"'}
                ],
                "UserPromptSubmit": [
                    {"command": 'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/claude-hook.py"'}
                ],
                "Stop": [
                    {"command": 'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/claude-hook.py"'}
                ],
            }
        }
        (hooks_dir / "hooks.json").write_text(
            json.dumps(hooks_json, indent=2) + "\n",
            encoding="utf-8",
        )

    def _emit_claude_md(self, core_root: Path, dest: Path) -> None:
        rules_dir = core_root / "rules"
        if not rules_dir.is_dir():
            return
        chunks: list[str] = ["# phase-flow v2\n"]
        for path in sorted(rules_dir.glob("*.mdc")):
            text = path.read_text(encoding="utf-8")
            if "alwaysApply: true" in text or "alwaysApply:true" in text:
                chunks.append(f"\n## {path.stem}\n\n{text}")
        if len(chunks) > 1:
            (dest / "CLAUDE.md").write_text("\n".join(chunks) + "\n", encoding="utf-8")


def emit(core_root: Path, repo_root: Path, dest: Path) -> None:
    descriptor_path = repo_root / "platforms" / "claude-code" / "descriptor.json"
    descriptor = EmitterBase.load_descriptor(descriptor_path)
    ClaudeCodeEmitter(descriptor).emit(core_root, repo_root, dest)
