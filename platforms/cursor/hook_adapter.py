"""Cursor hook I/O adapter — maps Cursor stdin/stdout to guardrail_core."""

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


def run_session_start(repo_root: Path) -> int:
    payload = read_stdin_json()
    root = workspace_root(payload)
    template = repo_root / "hooks" / "session-context.md"
    if not template.is_file():
        template = repo_root / "core" / "hooks" / "session-context.md"
    try:
        context = build_session_context(root, plugin_root(repo_root), template)
        print(json.dumps({"additional_context": context}, ensure_ascii=False))
        return 0
    except Exception as exc:  # noqa: BLE001 — session hook is fail-open
        print(json.dumps({"additional_context": f"(phase-flow v2 hook degraded: {exc})"}))
        return 0


def run_before_submit(repo_root: Path) -> int:
    payload = read_stdin_json()
    root = workspace_root(payload)
    try:
        result = evaluate_submit_guard(root, plugin_root(repo_root))
        _emit_submit_result(result)
        return 0
    except Exception as exc:  # noqa: BLE001 — submit hook is fail-closed
        _emit_submit_result(
            SubmitGuardResult(allow=False, message=f"phase-flow v2 guardrail hook error: {exc}")
        )
        return 0


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


def _emit_submit_result(result: SubmitGuardResult) -> None:
    if result.allow:
        print(json.dumps({"continue": True}))
    else:
        print(json.dumps({"continue": False, "user_message": result.message}))


def run_before_submit_from_payload(repo_root: Path, payload: dict) -> SubmitGuardResult:
    """Test helper — evaluate submit guard without stdin/stdout."""
    root = workspace_root(payload)
    try:
        return evaluate_submit_guard(root, plugin_root(repo_root))
    except Exception as exc:  # noqa: BLE001
        return SubmitGuardResult(allow=False, message=f"phase-flow v2 guardrail hook error: {exc}")


def emit_before_submit_stdout(result: SubmitGuardResult) -> str:
    if result.allow:
        return json.dumps({"continue": True})
    return json.dumps({"continue": False, "user_message": result.message})
