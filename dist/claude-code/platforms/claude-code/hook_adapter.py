"""Claude Code hook I/O adapter — maps Claude stdin/stdout to guardrail_core."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from guardrail_core import (
    SubmitGuardResult,
    build_session_context,
    evaluate_stop_sync,
    evaluate_submit_guard,
)
from pf_hook_util import read_stdin_json, workspace_root


def plugin_root(repo_root: Path) -> Path:
    return repo_root


def _hook_event(payload: dict) -> str:
    name = payload.get("hook_event_name") or payload.get("event") or ""
    return str(name)


def _session_context_template(repo_root: Path) -> Path:
    template = repo_root / "hooks" / "session-context.md"
    if template.is_file():
        return template
    return repo_root / "core" / "hooks" / "session-context.md"


def run_session_start(repo_root: Path) -> int:
    payload = read_stdin_json()
    root = workspace_root(payload)
    template = _session_context_template(repo_root)
    try:
        context = build_session_context(root, plugin_root(repo_root), template)
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "additionalContext": context,
                    }
                },
                ensure_ascii=False,
            )
        )
        return 0
    except Exception as exc:  # noqa: BLE001 — session hook is fail-open
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "additionalContext": f"(phase-flow v2 hook degraded: {exc})",
                    }
                }
            )
        )
        return 0


def run_user_prompt_submit(repo_root: Path) -> int:
    payload = read_stdin_json()
    root = workspace_root(payload)
    try:
        result = evaluate_submit_guard(root, plugin_root(repo_root))
        return _emit_submit_result(result)
    except Exception as exc:  # noqa: BLE001 — submit hook is fail-closed
        return _emit_submit_result(
            SubmitGuardResult(allow=False, message=f"phase-flow v2 guardrail hook error: {exc}")
        )


def run_stop(repo_root: Path) -> int:
    payload = read_stdin_json()
    root = workspace_root(payload)
    try:
        result = evaluate_stop_sync(payload, root)
        if result.followup_message:
            print(json.dumps({"followup_message": result.followup_message}, ensure_ascii=False))
        else:
            print(json.dumps({}))
        return 0
    except Exception as exc:  # noqa: BLE001 — stop hook is fail-open
        print(json.dumps({}))
        print(f"phase-flow memory-sync-stop hook degraded: {exc}", file=sys.stderr)
        return 0


def dispatch(repo_root: Path) -> int:
    payload = read_stdin_json()
    event = _hook_event(payload).lower()
    if event in {"sessionstart", "session_start"}:
        # Re-feed payload via module-level hack: write to a temp approach
        return _run_session_with_payload(repo_root, payload)
    if event in {"userpromptsubmit", "user_prompt_submit", "beforesubmitprompt"}:
        return _run_submit_with_payload(repo_root, payload)
    if event == "stop":
        return _run_stop_with_payload(repo_root, payload)
    # Unknown event — allow
    print(json.dumps({}))
    return 0


def _run_session_with_payload(repo_root: Path, payload: dict) -> int:
    root = workspace_root(payload)
    template = _session_context_template(repo_root)
    try:
        context = build_session_context(root, plugin_root(repo_root), template)
        print(
            json.dumps(
                {"hookSpecificOutput": {"additionalContext": context}},
                ensure_ascii=False,
            )
        )
        return 0
    except Exception as exc:  # noqa: BLE001
        print(
            json.dumps(
                {"hookSpecificOutput": {"additionalContext": f"(phase-flow v2 hook degraded: {exc})"}}
            )
        )
        return 0


def _run_submit_with_payload(repo_root: Path, payload: dict) -> int:
    root = workspace_root(payload)
    try:
        result = evaluate_submit_guard(root, plugin_root(repo_root))
        return _emit_submit_result(result)
    except Exception as exc:  # noqa: BLE001
        return _emit_submit_result(
            SubmitGuardResult(allow=False, message=f"phase-flow v2 guardrail hook error: {exc}")
        )


def _run_stop_with_payload(repo_root: Path, payload: dict) -> int:
    root = workspace_root(payload)
    try:
        result = evaluate_stop_sync(payload, root)
        if result.followup_message:
            print(json.dumps({"followup_message": result.followup_message}, ensure_ascii=False))
        else:
            print(json.dumps({}))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({}))
        print(f"phase-flow memory-sync-stop hook degraded: {exc}", file=sys.stderr)
        return 0


def _emit_submit_result(result: SubmitGuardResult) -> int:
    if result.allow:
        print(json.dumps({"decision": "approve"}))
        return 0
    print(json.dumps({"decision": "block", "reason": result.message}))
    return 2


def run_user_prompt_submit_from_payload(repo_root: Path, payload: dict) -> tuple[int, str]:
    """Test helper — returns (exit_code, stdout_json)."""
    root = workspace_root(payload)
    try:
        result = evaluate_submit_guard(root, plugin_root(repo_root))
    except Exception as exc:  # noqa: BLE001
        result = SubmitGuardResult(allow=False, message=f"phase-flow v2 guardrail hook error: {exc}")
    if result.allow:
        return 0, json.dumps({"decision": "approve"})
    return 2, json.dumps({"decision": "block", "reason": result.message})
