"""Claude Code hook stdout helpers (PRD 352 R14 / TR4).

Builds the upstream ``hookSpecificOutput`` nesting documented by Claude Code:
https://code.claude.com/docs/en/hooks
"""

from __future__ import annotations

from typing import Any, Mapping


def build_claude_hook_response(
    *,
    hook_event_name: str,
    permission_decision: str | None = None,
    permission_decision_reason: str | None = None,
    additional_context: str | None = None,
    updated_input: Mapping[str, Any] | None = None,
    decision: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Return a Claude Code hook JSON object with correct ``hookSpecificOutput`` nesting.

    Keyword arguments
    -----------------
    hook_event_name:
        Upstream ``hookEventName`` value (e.g. ``\"SessionStart\"``, ``\"PreToolUse\"``,
        ``\"UserPromptSubmit\"``).
    permission_decision:
        PreToolUse-only ``permissionDecision`` (``\"allow\"`` / ``\"deny\"`` / ``\"ask\"``).
        Omit for events that do not use permission decisions.
    permission_decision_reason:
        Optional reason paired with ``permission_decision``.
    additional_context:
        SessionStart / UserPromptSubmit ``additionalContext`` string.
    updated_input:
        Optional PreToolUse ``updatedInput`` mutation payload.
    decision:
        Top-level UserPromptSubmit control. Use ``\"block\"`` to deny; **omit on allow**
        (do not emit ``\"approve\"``).
    reason:
        Top-level reason shown when ``decision=\"block\"``.

    Returns
    -------
    dict
        JSON-serialisable hook response. Always includes ``hookSpecificOutput`` when any
        hook-specific field is set; top-level ``decision`` is included only when provided.
    """
    specific: dict[str, Any] = {"hookEventName": hook_event_name}
    if permission_decision is not None:
        specific["permissionDecision"] = permission_decision
    if permission_decision_reason is not None:
        specific["permissionDecisionReason"] = permission_decision_reason
    if additional_context is not None:
        specific["additionalContext"] = additional_context
    if updated_input is not None:
        specific["updatedInput"] = dict(updated_input)

    out: dict[str, Any] = {"hookSpecificOutput": specific}
    if decision is not None:
        out["decision"] = decision
    if reason is not None:
        out["reason"] = reason
    return out
