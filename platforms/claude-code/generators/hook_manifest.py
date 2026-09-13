"""Claude Code hook manifest builder (PRD 349 R1 / R19)."""

from __future__ import annotations

from typing import Any

from event_registry import _load_events_document, unsupported_events

_DEFAULT_COMMAND = 'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/claude-hook.py"'


def _unsupported_canonical_names(host: str = "claude-code") -> frozenset[str]:
    names: set[str] = set()
    for row in unsupported_events(host):
        canonical = row.get("canonical")
        if isinstance(canonical, str) and canonical.strip():
            names.add(canonical.strip())
    return frozenset(names)


def _pre_tool_host_name(host: str = "claude-code") -> str:
    """Resolve the host PreToolUse name from events.json via emitter_params."""
    for entry in _load_events_document()["events"]:
        if not isinstance(entry, dict):
            continue
        params = entry.get("emitter_params") or []
        if "tool_name_map" not in params:
            continue
        hosts = entry.get("hosts") or {}
        if not isinstance(hosts, dict):
            continue
        host_name = hosts.get(host)
        if isinstance(host_name, str) and host_name.strip():
            return host_name.strip()
    raise RuntimeError("events.json missing tool_name_map emitter_params entry")


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
    pre_tool = _pre_tool_host_name()
    for event in events:
        matcher = pre_tool_matcher if event == pre_tool else ""
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
    blocked = _unsupported_canonical_names()
    for event, groups in hooks.items():
        if event in blocked:
            errors.append(f"{event} must not be registered")
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
                if "command" not in handler:
                    errors.append(f"{event}[{idx}].hooks[{h_idx}]: missing command")
    return errors
