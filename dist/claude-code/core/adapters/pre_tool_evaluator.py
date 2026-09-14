"""Shared pre-tool evaluator with adapter-level tool-name mapping (PRD 349 R3).

PRD 352 R14–R17: Claude hook payloads go through ``build_claude_hook_response``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .claude_hook_helpers import build_claude_hook_response


@dataclass(frozen=True)
class PreToolVerdict:
    verdict: str  # pass | fail | unrecognised
    cause: str | None = None
    agent: str | None = None
    model_id: str | None = None
    tier: str | None = None
    intensity: str | None = None
    dispatch_id: str | None = None
    remediation: str | None = None
    canonical_tool: str | None = None
    host_tool: str | None = None

    def to_claude_hook_output(self) -> dict[str, Any]:
        """Claude Code PreToolUse shape — ``hookSpecificOutput.permissionDecision`` (R14/R18)."""
        match self.verdict:
            case "pass":
                updated: dict[str, Any] | None = None
                if self.model_id:
                    updated = {
                        "model": self.model_id,
                        "metadata": {
                            "dispatchId": self.dispatch_id,
                            "intensity": self.intensity,
                        },
                    }
                return build_claude_hook_response(
                    hook_event_name="PreToolUse",
                    permission_decision="allow",
                    updated_input=updated,
                )
            case "fail":
                return build_claude_hook_response(
                    hook_event_name="PreToolUse",
                    permission_decision="deny",
                    permission_decision_reason=(
                        f"Shipwright model-tier binding: {self.cause or 'no-model-resolved'}"
                    ),
                )
            case "unrecognised":
                return build_claude_hook_response(
                    hook_event_name="PreToolUse",
                    permission_decision="deny",
                    permission_decision_reason=(
                        f"Shipwright pre-tool: unrecognised tool {self.host_tool!r}"
                    ),
                )
            case _:
                raise NotImplementedError(self.verdict)


def _session_start_payload(context: str) -> dict[str, Any]:
    """Claude SessionStart structured output (PRD 352 R15).

    Emits ``hookSpecificOutput.hookEventName: \"SessionStart\"`` and nests
    ``additionalContext``. Does **not** invent a top-level ``event_name``.
    """
    return build_claude_hook_response(
        hook_event_name="SessionStart",
        additional_context=context,
    )


def _submit_result_payload(*, allow: bool, message: str = "") -> dict[str, Any]:
    """UserPromptSubmit payload (PRD 352 R16).

    Allow path omits ``decision`` entirely. Block path uses ``decision: \"block\"`` only.
    """
    if allow:
        return build_claude_hook_response(hook_event_name="UserPromptSubmit")
    return build_claude_hook_response(
        hook_event_name="UserPromptSubmit",
        decision="block",
        reason=message or "blocked",
    )


def _emit_submit_result(result: Any) -> dict[str, Any]:
    """Map a submit-guard result object to a Claude UserPromptSubmit payload (R16)."""
    allow = bool(getattr(result, "allow", False))
    message = str(getattr(result, "message", "") or "")
    return _submit_result_payload(allow=allow, message=message)


def fail_closed_pretool_deny(message: str) -> dict[str, Any]:
    """Fail-closed PreToolUse deny used when the hook itself crashes (PRD 352 R17)."""
    return build_claude_hook_response(
        hook_event_name="PreToolUse",
        permission_decision="deny",
        permission_decision_reason=message,
    )


def evaluate_pre_tool(
    payload: Mapping[str, Any],
    root: Path,
    *,
    tool_name_map: Mapping[str, str] | None = None,
    map_tool_name: Callable[[str], str | None] | None = None,
    evaluate_bound: Callable[[dict[str, Any], Path], Any] | None = None,
) -> PreToolVerdict:
    """Apply adapter tool-name map, then run the bound evaluator.

    Unmapped host tool names return ``unrecognised`` — never ``skip``.
    """
    host_tool = str(payload.get("tool_name") or payload.get("toolName") or "")
    canonical: str | None
    if map_tool_name is not None:
        canonical = map_tool_name(host_tool)
    elif tool_name_map is not None:
        if host_tool in tool_name_map:
            canonical = tool_name_map[host_tool]
        elif host_tool:
            # Unknown relative to the provided map → unrecognised.
            canonical = None
        else:
            canonical = None
    else:
        canonical = host_tool or None

    if not host_tool or canonical is None:
        return PreToolVerdict(
            verdict="unrecognised",
            cause="unmapped-tool-name",
            host_tool=host_tool or None,
            remediation="register the host tool in the adapter tool_name_map",
        )

    mapped_payload = dict(payload)
    mapped_payload["tool_name"] = canonical

    if evaluate_bound is None:
        from before_task_dispatch import evaluate_pre_tool_use  # noqa: PLC0415

        evaluate_bound = evaluate_pre_tool_use
    bound = evaluate_bound(mapped_payload, root)
    bound_verdict = str(getattr(bound, "verdict", "") or "")

    match bound_verdict:
        case "pass":
            return PreToolVerdict(
                verdict="pass",
                agent=getattr(bound, "agent", None),
                model_id=getattr(bound, "model_id", None),
                tier=getattr(bound, "tier", None),
                intensity=getattr(bound, "intensity", None),
                dispatch_id=getattr(bound, "dispatch_id", None),
                canonical_tool=canonical,
                host_tool=host_tool,
            )
        case "fail":
            return PreToolVerdict(
                verdict="fail",
                cause=getattr(bound, "cause", None),
                remediation=getattr(bound, "remediation", None),
                agent=getattr(bound, "agent", None),
                dispatch_id=getattr(bound, "dispatch_id", None),
                canonical_tool=canonical,
                host_tool=host_tool,
            )
        case "skip":
            # Mapped tools are recognised; skip-from-bound means "no binding work"
            # and must not be reported as skip to Claude (AS1 / R3).
            return PreToolVerdict(
                verdict="pass",
                cause="recognised-no-binding",
                canonical_tool=canonical,
                host_tool=host_tool,
            )
        case "unrecognised":
            return PreToolVerdict(
                verdict="unrecognised",
                cause=getattr(bound, "cause", None) or "unmapped-tool-name",
                host_tool=host_tool,
                canonical_tool=canonical,
            )
        case _:
            raise NotImplementedError(bound_verdict)
