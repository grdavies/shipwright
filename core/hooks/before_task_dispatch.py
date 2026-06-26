"""Pre-Task dispatch model binding (PRD 012 R5).

Resolves reviewer/persona/native-panel Task calls via resolve-model-tier.sh --agent and
attempts to inject the concrete model ID via preToolUse updated_input.

**Forward-compatible registration (Option C, 2026-06-26):** Registered in hooks.json for both
Cursor and Claude Code. Whether the platform honors updated_input.model on Task calls is
unverified for both platforms (DL-2 spike confirmed Cursor silently ignores it; Claude Code
unverified due to missing environment). The hook fires, logs its mutation attempt to stderr,
and fails open on unexpected errors. Phase 2 reviewer-dispatch-check.sh remains the
enforcement floor regardless of hook effectiveness.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sw_hook_util import workspace_root

_REVIEWER_AGENT = re.compile(r"^sw-[a-z0-9-]+-reviewer$")
_TASK_TOOL_NAMES = frozenset({"Task", "task"})


@dataclass(frozen=True)
class DispatchResult:
    verdict: str  # pass | skip | fail
    agent: str | None = None
    model_id: str | None = None
    tier: str | None = None
    cause: str | None = None
    remediation: str | None = None

    def to_hook_output(self) -> dict[str, Any]:
        """Cursor preToolUse format."""
        if self.verdict == "skip":
            return {"permission": "allow"}
        if self.verdict == "fail":
            msg = self.remediation or self.cause or "reviewer dispatch binding failed"
            return {
                "permission": "deny",
                "user_message": f"Shipwright model-tier binding: {self.cause or 'blocked'}",
                "agent_message": msg,
            }
        return {
            "permission": "allow",
            "updated_input": {"model": self.model_id},
        }

    def to_claude_hook_output(self) -> dict[str, Any]:
        """Claude Code PreToolUse format.

        The decision field uses Claude Code's approve/block vocabulary.
        For pass verdict, mutation is logged to stderr by the caller; we attempt
        updated_input but cannot verify whether Claude Code honors it for Task calls.
        """
        if self.verdict == "skip":
            return {"decision": "approve"}
        if self.verdict == "fail":
            return {
                "decision": "block",
                "reason": f"Shipwright model-tier binding: {self.cause or 'no-model-resolved'}",
            }
        return {"decision": "approve", "updated_input": {"model": self.model_id}}


def agent_id_from_task_input(tool_input: dict[str, Any]) -> str | None:
    """Best-effort agent id from Task tool_input."""
    for key in ("subagent_type", "agent", "name"):
        raw = tool_input.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    desc = tool_input.get("description")
    if isinstance(desc, str) and _REVIEWER_AGENT.match(desc.strip()):
        return desc.strip()
    return None


def is_bound_agent(agent_id: str) -> bool:
    if _REVIEWER_AGENT.match(agent_id):
        return True
    return agent_id in _NATIVE_PANEL_IDS


# Native panel specialist ids (models.routing.agents defaults).
_NATIVE_PANEL_IDS = frozenset(
    {
        "correctness",
        "security",
        "adversarial",
        "data-migration",
        "maintainability",
        "scope-fidelity",
        "testing",
        "performance",
        "api-contract",
        "reliability",
        "ui-ux",
        "type-design",
        "comment-accuracy",
        "ai-native",
    }
)


def resolve_agent_model(root: Path, agent_id: str) -> DispatchResult:
    script = root / "scripts" / "resolve-model-tier.sh"
    if not script.is_file():
        return DispatchResult(
            verdict="fail",
            agent=agent_id,
            cause="no-model-resolved",
            remediation="scripts/resolve-model-tier.sh missing",
        )
    proc = subprocess.run(
        ["bash", str(script), "--agent", agent_id],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        data = json.loads(proc.stdout.strip() or "{}")
    except json.JSONDecodeError:
        data = {}
    model_id = data.get("modelId")
    tier = data.get("tier")
    if not model_id or tier == "inherit":
        return DispatchResult(
            verdict="fail",
            agent=agent_id,
            cause="no-model-resolved",
            remediation=f"bash scripts/resolve-model-tier.sh --agent {agent_id}",
        )
    return DispatchResult(verdict="pass", agent=agent_id, model_id=str(model_id), tier=str(tier))


def evaluate_pre_tool_use(payload: dict[str, Any], root: Path) -> DispatchResult:
    tool_name = str(payload.get("tool_name") or "")
    if tool_name not in _TASK_TOOL_NAMES:
        return DispatchResult(verdict="skip")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return DispatchResult(verdict="skip")
    agent_id = agent_id_from_task_input(tool_input)
    if not agent_id or not is_bound_agent(agent_id):
        return DispatchResult(verdict="skip")
    return resolve_agent_model(root, agent_id)


def run_stdio() -> int:
    """Cursor preToolUse entrypoint — reads stdin, writes hook output to stdout."""
    try:
        payload = json.load(sys.stdin)
    except (OSError, ValueError, json.JSONDecodeError):
        print(json.dumps({"permission": "allow"}))
        return 0
    try:
        root = workspace_root(payload)
        result = evaluate_pre_tool_use(payload, root)
        if result.verdict == "pass":
            print(
                f"sw-model-binding: preToolUse mutation attempted"
                f" model={result.model_id} agent={result.agent}",
                file=sys.stderr,
            )
        print(json.dumps(result.to_hook_output(), ensure_ascii=False))
    except Exception:  # noqa: BLE001 — fail-open; preflight check is the enforcement floor
        print(json.dumps({"permission": "allow"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(run_stdio())
