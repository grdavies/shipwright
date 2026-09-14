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
from sw_hook_util import read_stdin_json, workspace_root

# core/ is on sys.path via claude-hook.py (exposes ``adapters``).
try:
    from adapters.pre_tool_evaluator import (  # type: ignore
        _emit_submit_result as submit_result_payload,
        _session_start_payload,
        fail_closed_pretool_deny,
    )
except ImportError:  # pragma: no cover - package-style import
    from core.adapters.pre_tool_evaluator import (  # type: ignore
        _emit_submit_result as submit_result_payload,
        _session_start_payload,
        fail_closed_pretool_deny,
    )

# Re-export for golden harness / historical imports.
__all__ = [
    "build_mcp_config",
    "dispatch",
    "plugin_root",
    "run_session_start",
    "run_stop",
    "run_user_prompt_submit",
    "run_user_prompt_submit_from_payload",
    "_session_start_payload",
]


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
        print(json.dumps(_session_start_payload(context), ensure_ascii=False))
        return 0
    except Exception as exc:  # noqa: BLE001 — session context still emitted when degraded
        print(json.dumps(_session_start_payload(f"(Shipwright hook degraded: {exc})")))
        return 0


def run_user_prompt_submit(repo_root: Path) -> int:
    payload = read_stdin_json()
    root = workspace_root(payload)
    try:
        result = evaluate_submit_guard(root, plugin_root(repo_root))
        return _emit_submit_result(result)
    except Exception as exc:  # noqa: BLE001 — submit hook is fail-closed
        return _emit_submit_result(
            SubmitGuardResult(allow=False, message=f"Shipwright guardrail hook error: {exc}")
        )


def run_stop(repo_root: Path) -> int:
    payload = read_stdin_json()
    root = workspace_root(payload)
    try:
        # Still evaluate sync side-effects, but never emit followup_message (R5).
        evaluate_stop_sync(payload, root)
        print(json.dumps({}))
        return 0
    except Exception as exc:  # noqa: BLE001 — stop hook is fail-open
        print(json.dumps({}))
        print(f"Shipwright memory-sync-stop hook degraded: {exc}", file=sys.stderr)
        return 0


def dispatch(repo_root: Path) -> int:
    payload = read_stdin_json()
    event = _hook_event(payload).lower()
    if event in {"sessionstart", "session_start"}:
        return _run_session_with_payload(repo_root, payload)
    if event in {"userpromptsubmit", "user_prompt_submit", "beforesubmitprompt"}:
        return _run_submit_with_payload(repo_root, payload)
    if event == "stop":
        return _run_stop_with_payload(repo_root, payload)
    if event in {"pretooluse", "pre_tool_use"}:
        return _run_pre_tool_use_with_payload(repo_root, payload)
    print(json.dumps({}))
    return 0


def _run_session_with_payload(repo_root: Path, payload: dict) -> int:
    root = workspace_root(payload)
    template = _session_context_template(repo_root)
    try:
        context = build_session_context(root, plugin_root(repo_root), template)
        print(json.dumps(_session_start_payload(context), ensure_ascii=False))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(json.dumps(_session_start_payload(f"(Shipwright hook degraded: {exc})")))
        return 0


def _run_submit_with_payload(repo_root: Path, payload: dict) -> int:
    root = workspace_root(payload)
    try:
        result = evaluate_submit_guard(root, plugin_root(repo_root))
        return _emit_submit_result(result)
    except Exception as exc:  # noqa: BLE001
        return _emit_submit_result(
            SubmitGuardResult(allow=False, message=f"Shipwright guardrail hook error: {exc}")
        )


def _run_stop_with_payload(repo_root: Path, payload: dict) -> int:
    root = workspace_root(payload)
    try:
        evaluate_stop_sync(payload, root)
        print(json.dumps({}))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({}))
        print(f"Shipwright memory-sync-stop hook degraded: {exc}", file=sys.stderr)
        return 0


def _run_pre_tool_use_with_payload(repo_root: Path, payload: dict) -> int:
    root = workspace_root(payload)
    try:
        # core/ is on sys.path via claude-hook.py wrapper; adapters/ too.
        import importlib

        pre_mod = importlib.import_module("adapters.pre_tool_evaluator")
        map_mod = importlib.import_module("tool_name_map")
        result = pre_mod.evaluate_pre_tool(
            payload,
            root,
            tool_name_map=map_mod.TOOL_NAME_MAP,
            map_tool_name=map_mod.map_tool_name,
        )
        if result.verdict == "pass" and result.model_id:
            print(
                f"sw-model-binding: PreToolUse mutation attempted"
                f" model={result.model_id} agent={result.agent}",
                file=sys.stderr,
            )
        print(json.dumps(result.to_claude_hook_output(), ensure_ascii=False))
        return 0
    except Exception as exc:  # noqa: BLE001 — PRD 352 R17 fail-closed deny
        deny = fail_closed_pretool_deny(f"Shipwright before-task-dispatch hook error: {exc}")
        print(json.dumps(deny, ensure_ascii=False))
        print(f"Shipwright before-task-dispatch hook denied on error: {exc}", file=sys.stderr)
        return 0


def _emit_submit_result(result: SubmitGuardResult) -> int:
    """Emit UserPromptSubmit JSON (R16) and return process exit code."""
    payload = submit_result_payload(result)
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if result.allow else 2


def run_user_prompt_submit_from_payload(repo_root: Path, payload: dict) -> tuple[int, str]:
    """Test helper — returns (exit_code, stdout_json)."""
    root = workspace_root(payload)
    try:
        result = evaluate_submit_guard(root, plugin_root(repo_root))
    except Exception as exc:  # noqa: BLE001
        result = SubmitGuardResult(allow=False, message=f"Shipwright guardrail hook error: {exc}")
    body = json.dumps(submit_result_payload(result), ensure_ascii=False)
    return (0 if result.allow else 2), body


def build_mcp_config(repo_root, *, enabled: bool = True):
    """Per-adapter MCP config for Claude Code (PRD 349 R41) — distinct path from Codex/OpenCode."""
    if not enabled:
        return None
    repo_root = Path(repo_root)
    scripts = repo_root / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import shipwright_paths  # noqa: PLC0415 — scripts path injected above

    server = shipwright_paths.bounded_mcp_server_path(repo_root)
    config_path = shipwright_paths.bounded_mcp_config_path(repo_root, "claude-code")
    return {
        "adapter_id": "claude-code",
        "config_path": str(config_path),
        "mcpServers": {
            "shipwright-bounded": {
                "command": "python3",
                "args": [str(server)],
                "transport": "stdio",
            }
        },
    }
