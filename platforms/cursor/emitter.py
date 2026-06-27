"""Cursor platform emitter — produces dist/cursor/."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from emitter_base import EmitterBase, EmitterError, ensure_clean_dir, read_version

import sys

_REPO_SCRIPTS = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(_REPO_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_REPO_SCRIPTS))
from capability_trust import KERNEL_HOOK_SLOTS, MANIFEST_HOOK_SLOTS  # noqa: E402
# verify-presets.json emitted via emitter_base.SW_REFERENCE_CLOSED_EMIT

SUPPORTED = {
    "hooks": {"native"},
    "skills": {"native"},
    "commands": {"slash-md"},
    "rules": {"mdc"},
    "subagents": {"native"},
    "mcp": {"yes"},
    "memoryXport": {"mcp"},
}

_CURSOR_HOOK_SHIMS = {
    "before-submit-guardrails.py": '''#!/usr/bin/env python3
"""Thin Cursor entrypoint — delegates to platforms/cursor/hook_adapter."""
from __future__ import annotations
import sys
from pathlib import Path
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "core" / "hooks"))
sys.path.insert(0, str(_REPO / "platforms" / "cursor"))
import hook_adapter  # noqa: E402
if __name__ == "__main__":
    raise SystemExit(hook_adapter.run_before_submit(_REPO))
''',
    "session-start.py": '''#!/usr/bin/env python3
"""Thin Cursor entrypoint — delegates to platforms/cursor/hook_adapter."""
from __future__ import annotations
import sys
from pathlib import Path
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "core" / "hooks"))
sys.path.insert(0, str(_REPO / "platforms" / "cursor"))
import hook_adapter  # noqa: E402
if __name__ == "__main__":
    raise SystemExit(hook_adapter.run_session_start(_REPO))
''',
    "memory-sync-stop.py": '''#!/usr/bin/env python3
"""Thin Cursor entrypoint — delegates to platforms/cursor/hook_adapter."""
from __future__ import annotations
import sys
from pathlib import Path
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "core" / "hooks"))
sys.path.insert(0, str(_REPO / "platforms" / "cursor"))
import hook_adapter  # noqa: E402
if __name__ == "__main__":
    raise SystemExit(hook_adapter.run_stop(_REPO))
''',
    "before-task-dispatch.py": '''#!/usr/bin/env python3
"""Thin Cursor entrypoint — delegates to core before_task_dispatch (PRD 012 R5)."""
from __future__ import annotations
import sys
from pathlib import Path
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "core" / "hooks"))
import before_task_dispatch  # noqa: E402
if __name__ == "__main__":
    raise SystemExit(before_task_dispatch.run_stdio())
''',
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
        self._emit_plugin_manifest(repo_root, dest)
        self._emit_hooks(repo_root, dest)

    def _copy_runtime_support(self, core_root: Path, repo_root: Path, dest: Path) -> None:
        hooks_src = core_root / "hooks"
        if hooks_src.is_dir():
            if (dest / "core" / "hooks").exists():
                shutil.rmtree(dest / "core" / "hooks")
            shutil.copytree(hooks_src, dest / "core" / "hooks")
        adapter_src = repo_root / "platforms" / "cursor" / "hook_adapter.py"
        if adapter_src.is_file():
            plat_dir = dest / "platforms" / "cursor"
            plat_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(adapter_src, plat_dir / "hook_adapter.py")
        self.copy_closed_sw_reference(core_root, dest)

    def _emit_plugin_manifest(self, repo_root: Path, dest: Path) -> None:
        manifest_dir = dest / ".cursor-plugin"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        plugin = {
            "name": "shipwright",
            "version": read_version(repo_root),
            "description": "Shipwright (generated)",
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
        template_src = repo_root / "core" / "hooks" / "session-context.md"
        if template_src.is_file():
            shutil.copy2(template_src, hooks_dir / "session-context.md")
        for name, body in _CURSOR_HOOK_SHIMS.items():
            path = hooks_dir / name
            path.write_text(body, encoding="utf-8")
            path.chmod(0o755)
        for extra in ("sw_recallium_url.py", "pre-commit", "pre-commit-frozen.sh"):
            src = repo_root / "hooks" / extra
            if not src.is_file():
                src = repo_root / "core" / "hooks" / extra
            if src.is_file():
                shutil.copy2(src, hooks_dir / extra)
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
                "preToolUse": [
                    {"command": 'python3 "${CURSOR_PLUGIN_ROOT}/hooks/before-task-dispatch.py"'}
                ],
            },
            "kernelHookSlots": sorted(KERNEL_HOOK_SLOTS),
            "manifestHookSlots": sorted(MANIFEST_HOOK_SLOTS),
        }
        (hooks_dir / "hooks.json").write_text(
            json.dumps(hooks_json, indent=2) + "\n",
            encoding="utf-8",
        )


def emit(core_root: Path, repo_root: Path, dest: Path) -> None:
    descriptor_path = repo_root / "platforms" / "cursor" / "descriptor.json"
    descriptor = EmitterBase.load_descriptor(descriptor_path)
    CursorEmitter(descriptor).emit(core_root, repo_root, dest)
