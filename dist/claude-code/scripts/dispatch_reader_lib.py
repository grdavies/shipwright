"""Reader/actor split enforcement for untrusted-signal intake (PRD 064 R9/R10)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Boundaries where role: reader is default-on (fail-closed when missing).
READER_DEFAULT_ON_BOUNDARIES = frozenset({
    "feedback-intake",
    "debug-sentry-expansion",
})

MUTATING_TOOL_NAMES = frozenset({
    "Write",
    "StrReplace",
    "Delete",
    "ApplyPatch",
    "EditNotebook",
    "Shell",
})


def boundary_requires_reader(boundary: str | None) -> bool:
    if not boundary:
        return False
    return boundary.strip() in READER_DEFAULT_ON_BOUNDARIES


def evaluate_reader_role(
    *,
    role: str | None,
    boundary: str | None,
    override: bool = False,
) -> dict[str, Any] | None:
    """Fail closed when a default-on boundary lacks role: reader."""
    if not boundary_requires_reader(boundary):
        return None
    normalized = (role or "").strip().lower()
    if normalized == "reader":
        return None
    if override:
        return None
    return {
        "verdict": "fail",
        "cause": "binding:reader-role-missing",
        "boundary": boundary,
        "role": role,
        "retryable": False,
        "remediation": (
            "spawn a reader Task with declared field role: reader and readonly: true; "
            "the acting agent must never receive raw untrusted payload"
        ),
    }


def load_tool_log(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        calls = raw.get("toolCalls") or raw.get("tool_calls") or raw.get("calls")
        if isinstance(calls, list):
            return [item for item in calls if isinstance(item, dict)]
    return []


def validate_reader_tool_log(tool_log: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Fail closed when a reader-role Task log shows a mutating tool call."""
    for entry in tool_log:
        name = entry.get("toolName") or entry.get("tool_name") or entry.get("name")
        if not isinstance(name, str):
            continue
        if name in MUTATING_TOOL_NAMES:
            return {
                "verdict": "fail",
                "cause": "binding:reader-mutating-call",
                "toolName": name,
                "retryable": False,
                "remediation": (
                    "reader Tasks may only ingest and redact; return enveloped signal JSON "
                    "without mutating repository state"
                ),
            }
    return None


def validate_reader_tool_log_file(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return {
            "verdict": "fail",
            "cause": "binding:reader-tool-log-missing",
            "toolLogPath": str(path),
            "retryable": False,
            "remediation": "persist reader Task tool-call log before post-spawn validation",
        }
    return validate_reader_tool_log(load_tool_log(path))
