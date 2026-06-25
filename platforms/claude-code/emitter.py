"""Claude Code platform emitter — produces dist/claude-code/."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from emitter_base import EmitterBase, EmitterError, ensure_clean_dir, read_version

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

    def emit(self, core_root: Path, repo_root: Path, dest: Path) -> None:
        self.validate_descriptor()
        ensure_clean_dir(dest)
        self.copy_emittable_content(core_root, dest)
        self._apply_use_when_to_skills(core_root, dest)
        self._copy_runtime_support(core_root, repo_root, dest)
        self._emit_plugin_manifest(repo_root, dest)
        self._emit_hooks(repo_root, dest)
        self._emit_claude_md(core_root, dest)

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
        return f"---{frontmatter}---{body}"

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
            shutil.copytree(hooks_src, dest / "core" / "hooks")
        adapter_src = repo_root / "platforms" / "claude-code" / "hook_adapter.py"
        if adapter_src.is_file():
            plat_dir = dest / "platforms" / "claude-code"
            plat_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(adapter_src, plat_dir / "hook_adapter.py")
        comm_defaults = core_root / "sw-reference" / "communication-routing.defaults.json"
        if comm_defaults.is_file():
            ref_dir = dest / "core" / "sw-reference"
            ref_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(comm_defaults, ref_dir / "communication-routing.defaults.json")

    def _emit_plugin_manifest(self, repo_root: Path, dest: Path) -> None:
        manifest_dir = dest / ".claude-plugin"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        plugin = {
            "name": "shipwright",
            "version": read_version(repo_root),
            "description": "Shipwright for Claude Code (generated)",
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
        chunks: list[str] = ["# Shipwright\n"]
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
