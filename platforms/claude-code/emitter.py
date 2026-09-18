"""Claude Code platform emitter — produces dist/claude-code/."""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

from emitter_base import EmitterBase, EmitterError, restore_safe_emit_directory, read_version
# verify-presets.json emitted via emitter_base.SW_REFERENCE_CLOSED_EMIT

import sys as _sys

_GENERATORS = Path(__file__).resolve().parent / "generators"
if str(_GENERATORS) not in _sys.path:
    _sys.path.insert(0, str(_GENERATORS))

from event_registry import (  # noqa: E402
    assert_no_context_switch_registration,
    registered_host_events,
    unsupported_events,
)
from hook_manifest import (  # noqa: E402
    build_hooks_manifest,
    validate_native_hooks_manifest,
)

ALWAYS_APPLY_SKILL_REL = Path("skills") / "sw-always-apply" / "SKILL.md"


class BuildError(EmitterError):
    """Fail-closed when a required Claude Code emit target cannot be resolved."""


SUPPORTED = {
    "hooks": {"native"},
    "skills": {"native"},
    "commands": {"slash-md"},
    "rules": {"claude-md"},
    "subagents": {"native"},
    "mcp": {"yes"},
    "memoryXport": {"mcp"},
}

RULE_SKILL_ALIASES = {
    "code-review-automation": "stabilize-loop",
    "sw-workflow-sequencing": "worktree",
    "memory-guardrails": "memory",
    "checks-gate": "checks-gate",
    "sw-subagent-dispatch": "parallelism",
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

    def _emit_impl(self, core_root: Path, repo_root: Path, dest: Path) -> None:
        self.validate_descriptor()
        with restore_safe_emit_directory(dest) as emit_dest:
            self.copy_emittable_content(core_root, emit_dest)
            if os.environ.get("SHIPWRIGHT_EMITTER_INJECT_FAIL") == "1":
                raise EmitterError("injected failure for restore-safe emit harness")
            self.emit_zipapp_runtime(repo_root, emit_dest)
            self._apply_use_when_to_skills(core_root, emit_dest)
            self._copy_runtime_support(core_root, repo_root, emit_dest)
            self._emit_plugin_manifest(repo_root, emit_dest)
            self._emit_install_version(repo_root, emit_dest)
            self.copy_install_root_documentation(core_root, emit_dest)
            self._emit_installer_entrypoint(emit_dest)
            self._emit_hooks(repo_root, emit_dest)
            self._emit_claude_md(core_root, emit_dest)

    @staticmethod
    def _rule_use_when_description(rule_text: str) -> str | None:
        if "alwaysApply: true" in rule_text or "alwaysApply:true" in rule_text:
            return None
        match = re.search(r"^description:\s*(.+)$", rule_text, re.MULTILINE)
        if not match:
            return None
        desc = match.group(1).strip().strip('"').strip("'")
        if "USE WHEN" not in desc.upper():
            return None
        return desc

    @staticmethod
    def _skill_path_for_rule(
        rule_path: Path, rule_text: str, core_root: Path, dest: Path
    ) -> Path | None:
        stem = rule_path.stem
        skill_name = RULE_SKILL_ALIASES.get(stem, stem)
        candidate = dest / "skills" / skill_name / "SKILL.md"
        if candidate.is_file():
            return candidate
        ref = re.search(r"skills/([a-z0-9-]+)/", rule_text)
        if ref:
            candidate = dest / "skills" / ref.group(1) / "SKILL.md"
            if candidate.is_file():
                return candidate
        if (core_root / "skills" / skill_name).is_dir():
            return dest / "skills" / skill_name / "SKILL.md"
        return None

    @staticmethod
    def _prepend_use_when_to_skill(skill_text: str, use_when: str) -> str:
        if use_when in skill_text:
            return skill_text
        if not skill_text.startswith("---"):
            return skill_text
        end = skill_text.find("\n---", 3)
        if end == -1:
            return skill_text
        frontmatter = skill_text[3:end]
        body = skill_text[end + 4 :]
        if re.search(r"^description:\s*", frontmatter, re.MULTILINE):

            def _merge(match: re.Match[str]) -> str:
                existing = match.group(2).strip()
                if use_when in existing:
                    return match.group(0)
                return f"{match.group(1)}{use_when} {existing}"

            frontmatter = re.sub(
                r"^(description:\s*)(.+)$",
                _merge,
                frontmatter,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            frontmatter = f"description: {use_when}\n{frontmatter}"
        return f"---\n{frontmatter}\n---\n{body}"

    def _apply_use_when_to_skills(self, core_root: Path, dest: Path) -> None:
        rules_dir = core_root / "rules"
        if not rules_dir.is_dir():
            return
        for rule_path in sorted(rules_dir.glob("*.mdc")):
            rule_text = rule_path.read_text(encoding="utf-8")
            use_when = self._rule_use_when_description(rule_text)
            if not use_when:
                continue
            skill_path = self._skill_path_for_rule(rule_path, rule_text, core_root, dest)
            if skill_path is None or not skill_path.is_file():
                continue
            updated = self._prepend_use_when_to_skill(
                skill_path.read_text(encoding="utf-8"),
                use_when,
            )
            skill_path.write_text(updated, encoding="utf-8")

    def _copy_runtime_support(self, core_root: Path, repo_root: Path, dest: Path) -> None:
        hooks_src = core_root / "hooks"
        if hooks_src.is_dir():
            dest_hooks = dest / "core" / "hooks"
            dest_hooks.mkdir(parents=True, exist_ok=True)
            for item in hooks_src.iterdir():
                if item.suffix == ".sh" and (item.with_suffix(".py")).is_file():
                    continue
                if item.name in ("pre-commit", "pre-push", "commit-msg") and not item.suffix:
                    continue
                if item.is_dir():
                    shutil.copytree(item, dest_hooks / item.name)
                elif item.is_file():
                    shutil.copy2(item, dest_hooks / item.name)
        adapter_src = repo_root / "platforms" / "claude-code" / "hook_adapter.py"
        if adapter_src.is_file():
            plat_dir = dest / "platforms" / "claude-code"
            plat_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(adapter_src, plat_dir / "hook_adapter.py")
        self.copy_closed_sw_reference(core_root, dest)

    def _emit_install_version(self, repo_root: Path, dest: Path) -> None:
        """Emit canonical semver at install root for pure-install drift checks (PRD 338 R27)."""
        (dest / "version.txt").write_text(read_version(repo_root) + "\n", encoding="utf-8")

    def _emit_installer_entrypoint(self, dest: Path) -> None:
        """Emit install-root-relative installer shim wired to packaged install.py (PRD 338 R29)."""
        scripts_dir = dest / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        env_name = self.plugin_root_env_name()
        shim = f'''#!/usr/bin/env python3
"""Claude Code installer entrypoint — delegates to packaged install.py (PRD 338 R29)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
_PLUGIN_ROOT_ENV = "{env_name}"


def _resolve_pyz(plugin_root: Path) -> Path:
    stable = plugin_root / "shipwright.pyz"
    if stable.is_file():
        return stable
    candidates = sorted(plugin_root.glob("shipwright-*.pyz"))
    if not candidates:
        raise FileNotFoundError(f"no shipwright.pyz under {{plugin_root}}")
    return candidates[-1]


def main() -> int:
    env = os.environ.copy()
    env.setdefault(_PLUGIN_ROOT_ENV, str(_PLUGIN_ROOT))
    pyz = _resolve_pyz(_PLUGIN_ROOT)
    cmd = [
        sys.executable,
        str(pyz),
        "install.py",
        "--integration",
        "claude-code",
        *sys.argv[1:],
    ]
    return subprocess.call(cmd, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
'''
        path = scripts_dir / "install.py"
        path.write_text(shim, encoding="utf-8")
        path.chmod(0o755)

    def _emit_plugin_manifest(self, repo_root: Path, dest: Path) -> None:
        manifest_dir = dest / ".claude-plugin"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        version = read_version(repo_root)
        plugin = {
            "name": "shipwright",
            "version": version,
            "description": "Shipwright for Claude Code (generated)",
            "installer": "./scripts/install.py",
        }
        (manifest_dir / "plugin.json").write_text(
            json.dumps(plugin, indent=2) + "\n",
            encoding="utf-8",
        )

    def _emit_hooks(self, repo_root: Path, dest: Path) -> None:
        adapter_src = repo_root / "platforms" / "claude-code" / "hook_adapter.py"
        hooks_dir = dest / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        template_src = repo_root / "core" / "hooks" / "session-context.md"
        if template_src.is_file():
            shutil.copy2(template_src, hooks_dir / "session-context.md")
        if adapter_src.is_file():
            shutil.copy2(adapter_src, hooks_dir / "hook_adapter.py")
        adapters_src = repo_root / "platforms" / "claude-code" / "adapters"
        if adapters_src.is_dir():
            dest_adapters = dest / "platforms" / "claude-code" / "adapters"
            dest_adapters.mkdir(parents=True, exist_ok=True)
            for item in adapters_src.iterdir():
                if item.is_file() and item.suffix == ".py":
                    shutil.copy2(item, dest_adapters / item.name)
        pre_tool_src = repo_root / "core" / "adapters" / "pre_tool_evaluator.py"
        if pre_tool_src.is_file():
            dest_core_adapters = dest / "core" / "adapters"
            dest_core_adapters.mkdir(parents=True, exist_ok=True)
            (dest_core_adapters / "__init__.py").write_text("", encoding="utf-8")
            shutil.copy2(pre_tool_src, dest_core_adapters / "pre_tool_evaluator.py")
        helpers_src = repo_root / "core" / "adapters" / "claude_hook_helpers.py"
        if helpers_src.is_file():
            shutil.copy2(helpers_src, dest_core_adapters / "claude_hook_helpers.py")
        wrapper = (
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "from pathlib import Path\n"
            "_REPO = Path(__file__).resolve().parent.parent\n"
            "sys.path.insert(0, str(_REPO / \"core\" / \"hooks\"))\n"
            "sys.path.insert(0, str(_REPO / \"core\"))\n"
            "sys.path.insert(0, str(_REPO / \"platforms\" / \"claude-code\"))\n"
            "sys.path.insert(0, str(_REPO / \"platforms\" / \"claude-code\" / \"adapters\"))\n"
            "import hook_adapter\n"
            "if __name__ == \"__main__\":\n"
            "    raise SystemExit(hook_adapter.dispatch(_REPO))\n"
        )
        (hooks_dir / "claude-hook.py").write_text(wrapper, encoding="utf-8")
        context_switch_shim = (
            "#!/usr/bin/env python3\n"
            '"""Thin Claude Code entrypoint — context-switch HandoffBundle export."""\n'
            "from __future__ import annotations\n"
            "import sys\n"
            "from pathlib import Path\n"
            "_REPO = Path(__file__).resolve().parent.parent\n"
            "sys.path.insert(0, str(_REPO / \"core\" / \"hooks\"))\n"
            "import context_switch_handoff  # noqa: E402\n"
            "if __name__ == \"__main__\":\n"
            "    raise SystemExit(context_switch_handoff.main())\n"
        )
        (hooks_dir / "context-switch-handoff.py").write_text(context_switch_shim, encoding="utf-8")
        (hooks_dir / "context-switch-handoff.py").chmod(0o755)

        events = registered_host_events("claude-code")
        assert_no_context_switch_registration(events)
        command = 'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/claude-hook.py"'
        hooks_json = build_hooks_manifest(events=events, command=command)
        unsupported = unsupported_events("claude-code")
        if unsupported:
            hooks_json["unsupportedEvents"] = unsupported
        errors = validate_native_hooks_manifest(hooks_json)
        if errors:
            raise BuildError(
                "claude-code hooks.json failed native schema checks: " + "; ".join(errors)
            )
        canonical_hooks = repo_root / "core" / "hooks" / "hooks.json"
        if canonical_hooks.is_file():
            hooks_json["canonicalManifest"] = str(canonical_hooks.relative_to(repo_root))
        (hooks_dir / "hooks.json").write_text(
            json.dumps(hooks_json, indent=2) + "\n",
            encoding="utf-8",
        )

    def _emit_claude_md(self, core_root: Path, dest: Path) -> None:
        """Place always-applied rules in the plugin skill context path (R4)."""
        rules_dir = core_root / "rules"
        if not rules_dir.is_dir():
            return
        chunks: list[str] = [
            "---",
            "name: sw-always-apply",
            "description: Shipwright always-applied guardrails for Claude Code sessions. Use when starting or continuing any Claude Code session with this plugin installed.",
            "---",
            "",
            "# Shipwright always-applied rules",
            "",
        ]
        found = False
        for path in sorted(rules_dir.glob("*.mdc")):
            rule_text = path.read_text(encoding="utf-8")
            if "alwaysApply: true" in rule_text or "alwaysApply:true" in rule_text:
                chunks.append(f"\n## {path.stem}\n\n{rule_text}")
                found = True
        if not found:
            return
        skills_root = dest / "skills"
        if not skills_root.exists():
            raise BuildError(
                "cannot resolve Claude Code plugin always-apply skill path: "
                f"{ALWAYS_APPLY_SKILL_REL} (skills/ missing under {dest})"
            )
        target = dest / ALWAYS_APPLY_SKILL_REL
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("\n".join(chunks) + "\n", encoding="utf-8")
        except OSError as exc:
            raise BuildError(
                f"cannot write always-apply rules to plugin skill path {ALWAYS_APPLY_SKILL_REL}: {exc}"
            ) from exc
        stale = dest / "CLAUDE.md"
        if stale.is_file():
            stale.unlink()


def emit(core_root: Path, repo_root: Path, dest: Path) -> None:
    descriptor_path = repo_root / "platforms" / "claude-code" / "descriptor.json"
    descriptor = EmitterBase.load_descriptor(descriptor_path)
    ClaudeCodeEmitter(descriptor).emit(core_root, repo_root, dest)
