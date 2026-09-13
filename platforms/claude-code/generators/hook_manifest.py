"""Claude Code hook manifest builder (PRD 349 R1)."""

from __future__ import annotations

from typing import Any

_DEFAULT_COMMAND = 'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/claude-hook.py"'


def build_matcher_group(command: str, *, matcher: str = "") -> dict[str, Any]:
    return {
        "matcher": matcher,
        "hooks": [{"type": "command", "command": command}],
    }


def build_hooks_manifest(
    *,
    events: list[str],
    command: str = _DEFAULT_COMMAND,
    pre_tool_matcher: str = "",
) -> dict[str, Any]:
    hooks_by_event: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        matcher = pre_tool_matcher if event == "PreToolUse" else ""
        hooks_by_event[event] = [build_matcher_group(command, matcher=matcher)]
    return {"hooks": hooks_by_event}


def is_legacy_event_command_form(document: dict[str, Any]) -> bool:
    hooks = document.get("hooks")
    if not isinstance(hooks, dict):
        return False
    for value in hooks.values():
        if not isinstance(value, list) or not value:
            continue
        first = value[0]
        if not isinstance(first, dict):
            continue
        if "command" in first and "hooks" not in first:
            return True
        inner = first.get("hooks")
        if isinstance(inner, list) and inner:
            handler = inner[0]
            if isinstance(handler, dict) and "command" in handler and handler.get("type") != "command":
                return True
    return False


def validate_native_hooks_manifest(document: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(document, dict):
        return ["manifest must be an object"]
    hooks = document.get("hooks")
    if not isinstance(hooks, dict):
        errors.append("hooks must be an object keyed by event name")
        return errors
    if is_legacy_event_command_form(document):
        errors.append("legacy Event:[{command}] form is forbidden")
    for event, groups in hooks.items():
        if event == "ContextSwitch":
            errors.append("ContextSwitch must not be registered")
        if not isinstance(groups, list):
            errors.append(f"{event}: matcher groups must be an array")
            continue
        for idx, group in enumerate(groups):
            if not isinstance(group, dict):
                errors.append(f"{event}[{idx}]: matcher group must be an object")
                continue
            if "matcher" not in group:
                errors.append(f"{event}[{idx}]: missing matcher")
            inner = group.get("hooks")
            if not isinstance(inner, list) or not inner:
                errors.append(f"{event}[{idx}]: hooks must be a non-empty array")
                continue
            for h_idx, handler in enumerate(inner):
                if not isinstance(handler, dict):
                    errors.append(f"{event}[{idx}].hooks[{h_idx}]: must be an object")
                    continue
                if handler.get("type") != "command":
                    errors.append(f"{event}[{idx}].hooks[{h_idx}]: type must be 'command'")
                if not isinstance(handler.get("command"), str) or not handler.get("command"):
                    errors.append(f"{event}[{idx}].hooks[{h_idx}]: command required")
    return errors
