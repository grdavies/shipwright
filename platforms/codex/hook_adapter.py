"""Codex hook/skill adapter — ships skill bodies and wires lifecycle (PRD 352 R4)."""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path


def command_skill_text(text: str, name: str) -> str:
    """Ensure Codex SKILL.md frontmatter includes ``name:`` matching the directory."""
    if not text.startswith("---"):
        return f"---\nname: {name}\ndescription: Shipwright {name}\n---\n\n{text}"
    rest = text[3:].lstrip("\n")
    closing = rest.find("\n---")
    if closing == -1:
        return f"---\nname: {name}\n{rest}"
    fm = rest[:closing]
    body = rest[closing:]
    if re.search(r"(?m)^name\s*:", fm):
        return text
    return f"---\nname: {name}\n{fm}{body}"


def copy_command_skills(core_root: Path, dest: Path) -> list[str]:
    """Project core/commands/*.md as Codex skills so ``$sw-init`` is invokable."""
    commands_src = core_root / "commands"
    written: list[str] = []
    if not commands_src.is_dir():
        return written
    skills_dest = dest / "skills"
    skills_dest.mkdir(parents=True, exist_ok=True)
    for cmd in sorted(commands_src.glob("*.md")):
        name = cmd.stem
        out_dir = skills_dest / name
        out_dir.mkdir(parents=True, exist_ok=True)
        body = command_skill_text(cmd.read_text(encoding="utf-8"), name)
        (out_dir / "SKILL.md").write_text(body, encoding="utf-8")
        written.append(f"skills/{name}/SKILL.md")
    return written


def copy_emittable_content(core_root: Path, dest: Path) -> list[str]:
    """Copy full skill bodies from core into the Codex package tree.

    Codex historically emitted ref stubs only (PRD 349 R21). PRD 352 R4 option (a)
    ships complete skill bodies so packaged installs remain self-contained.
    """
    skills_src = core_root / "skills"
    written: list[str] = []
    if not skills_src.is_dir():
        return written
    skills_dest = dest / "skills"
    skills_dest.mkdir(parents=True, exist_ok=True)
    for skill_dir in sorted(skills_src.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            continue
        out_dir = skills_dest / skill_dir.name
        if out_dir.exists():
            shutil.rmtree(out_dir)
        shutil.copytree(
            skill_dir,
            out_dir,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "tests", "test"),
        )
        written.append(f"skills/{skill_dir.name}/SKILL.md")
    return written


def _core_hooks_dir() -> Path:
    """Resolve core/hooks whether running from platforms/<host>/ or packaged hooks/."""
    here = Path(__file__).resolve().parent
    candidates = (
        here.parents[1] / "core" / "hooks",  # platforms/<host>/hook_adapter.py
        here.parent / "core" / "hooks",  # dist/<host>/hooks/hook_adapter.py
        here / "core" / "hooks",
    )
    for candidate in candidates:
        if (candidate / "before_task_dispatch.py").is_file():
            return candidate
    return candidates[0]


def before_task_dispatch_stdio(payload: dict | None = None) -> int:
    """Evaluate PreToolUse with Codex's native input and output contract.

    Codex updatedInput replaces the complete argument object. Keep the original
    arguments when adding model binding, and never emit Cursor permission fields.
    """
    try:
        # Keep the previous no-argument shim callable during an atomic file refresh.
        if payload is None:
            payload = json.load(sys.stdin)
            if not isinstance(payload, dict):
                raise ValueError("hook input must be an object")
            event = str(payload.get("hook_event_name") or payload.get("event") or "")
            if "".join(c for c in event.lower() if c.isalnum()) != "pretooluse":
                print(json.dumps({}))
                return 0
        hooks = _core_hooks_dir()
        if str(hooks) not in sys.path:
            sys.path.insert(0, str(hooks))
        from sw_hook_util import ensure_plugin_scripts_importable, workspace_root

        plugin_root = hooks.parent.parent
        ensure_plugin_scripts_importable(plugin_root)
        import before_task_dispatch

        normalized = dict(payload)
        normalized["tool_name"] = {
            "Bash": "Shell",
            "apply_patch": "ApplyPatch",
        }.get(payload.get("tool_name"), payload.get("tool_name"))
        result = before_task_dispatch.evaluate_pre_tool_use(
            normalized, workspace_root(payload)
        )
        output: dict = {}
        if result.verdict == "fail":
            output = _deny_output(result.remediation or result.cause or "policy denied")
        elif result.verdict == "pass" and result.model_id:
            tool_input = dict(payload.get("tool_input") or {})
            metadata = dict(tool_input.get("metadata") or {})
            metadata.update(dispatchId=result.dispatch_id, intensity=result.intensity)
            tool_input.update(model=result.model_id, metadata=metadata)
            output = {"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "updatedInput": tool_input,
            }}
        print(json.dumps(output, ensure_ascii=False))
    except Exception as exc:
        # Report a real policy denial, not a misleading successful fail-open hook.
        # Exception messages and payloads can contain credentials; log only type.
        reason = f"Shipwright Codex pre-tool evaluation failed ({type(exc).__name__})"
        print(reason, file=sys.stderr)
        print(json.dumps(_deny_output(reason + "; repair the installed hook runtime")))
    return 0


def _deny_output(reason: str) -> dict:
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}
