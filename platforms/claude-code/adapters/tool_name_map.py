"""Claude Code host tool-name → canonical tool-name map (PRD 349 R3)."""

from __future__ import annotations

# Claude Code tool names → Shipwright/Cursor-oriented canonical names used by
# the shared pre-tool evaluator.
TOOL_NAME_MAP: dict[str, str] = {
    "Agent": "Task",
    "Bash": "Shell",
    "Edit": "StrReplace",
    "Read": "Read",
    "Write": "Write",
    "MultiEdit": "MultiEdit",
    "Glob": "Glob",
    "Grep": "Grep",
    "WebFetch": "WebFetch",
    "WebSearch": "WebSearch",
    "TodoWrite": "TodoWrite",
    "Task": "Task",
}

# Names the shared evaluator already understands without mapping.
_CANONICAL_PASSTHROUGH = frozenset(
    {
        "Task",
        "task",
        "Shell",
        "shell",
        "Write",
        "StrReplace",
        "Delete",
        "ApplyPatch",
        "EditNotebook",
        "Read",
        "Glob",
        "Grep",
        "WebFetch",
        "WebSearch",
        "TodoWrite",
        "MultiEdit",
    }
)


def map_tool_name(host_tool_name: str) -> str | None:
    """Return canonical name, or None when the host name is unmapped."""
    if not host_tool_name:
        return None
    if host_tool_name in TOOL_NAME_MAP:
        return TOOL_NAME_MAP[host_tool_name]
    if host_tool_name in _CANONICAL_PASSTHROUGH:
        return host_tool_name
    return None
