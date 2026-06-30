"""Pre-Task dispatch model binding (PRD 012 R5).

Resolves reviewer/persona/native-panel Task calls via resolve-model-tier.py (R39b),
enforces a fresh dispatch-preflight nonce record keyed by dispatchId (R38),
and injects concrete model metadata.

**Forward-compatible registration (Option C, 2026-06-26):** Registered in hooks.json for both
Cursor and Claude Code. Whether the platform honors updated_input.model on Task calls is
unverified for both platforms (DL-2 spike confirmed Cursor silently ignores it; Claude Code
unverified due to missing environment). The hook fires, logs its mutation attempt to stderr,
and fails open on unexpected errors. `scripts/dispatch-check.py` remains the
enforcement floor regardless of hook effectiveness.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sw_hook_util import workspace_root

from memory_prework_gate import consume_record, validate_fresh_record, load_record

_REVIEWER_AGENT = re.compile(r"^sw-[a-z0-9-]+-reviewer$")
_TASK_TOOL_NAMES = frozenset({"Task", "task"})
_MUTATING_TOOL_NAMES = frozenset(
    {"Write", "StrReplace", "Delete", "ApplyPatch", "EditNotebook"}
)
_DISPATCH_PREFLIGHT_DIR = Path(".cursor/hooks/state/task-dispatch-preflight")
_DISPATCH_PREFLIGHT_LEGACY = Path(".cursor/hooks/state/task-dispatch-preflight.json")


@dataclass(frozen=True)
class DispatchResult:
    verdict: str  # pass | skip | fail
    agent: str | None = None
    model_id: str | None = None
    tier: str | None = None
    intensity: str | None = None
    dispatch_id: str | None = None
    command: str | None = None
    skill: str | None = None
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
            "updated_input": {
                "model": self.model_id,
                "metadata": {
                    "dispatchId": self.dispatch_id,
                    "intensity": self.intensity,
                },
            },
        }

    def to_claude_hook_output(self) -> dict[str, Any]:
        """Claude Code PreToolUse format."""
        if self.verdict == "skip":
            return {"decision": "approve"}
        if self.verdict == "fail":
            return {
                "decision": "block",
                "reason": f"Shipwright model-tier binding: {self.cause or 'no-model-resolved'}",
            }
        return {
            "decision": "approve",
            "updated_input": {
                "model": self.model_id,
                "metadata": {
                    "dispatchId": self.dispatch_id,
                    "intensity": self.intensity,
                },
            },
        }


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


def dispatch_id_from_task_input(tool_input: dict[str, Any]) -> str | None:
    """dispatchId from tool_input metadata or top-level field."""
    meta = tool_input.get("metadata")
    if isinstance(meta, dict):
        raw = meta.get("dispatchId")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    raw = tool_input.get("dispatchId")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
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


def resolve_dispatch_model(
    root: Path,
    agent_id: str,
    *,
    command: str | None = None,
    skill: str | None = None,
) -> DispatchResult:
    """Resolve model tier using R39b precedence via resolve-model-tier.py."""
    script = root / "scripts" / "resolve-model-tier.py"
    if not script.is_file():
        return DispatchResult(
            verdict="fail",
            agent=agent_id,
            cause="no-model-resolved",
            remediation="scripts/resolve-model-tier.py missing",
        )
    argv = [sys.executable, str(script), "--agent", agent_id]
    if command:
        argv.extend(["--command", command])
    proc = subprocess.run(argv, cwd=str(root), capture_output=True, text=True, check=False)
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
            remediation=f"python3 scripts/resolve-model-tier.py --agent {agent_id}",
        )
    return DispatchResult(verdict="pass", agent=agent_id, model_id=str(model_id), tier=str(tier))


def _read_preflight_record(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _list_unconsumed_preflights(root: Path, agent_id: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    now = int(time.time())
    keyed_dir = root / _DISPATCH_PREFLIGHT_DIR
    if keyed_dir.is_dir():
        for path in sorted(keyed_dir.glob("*.json")):
            rec = _read_preflight_record(path)
            if not rec:
                continue
            if rec.get("agent") != agent_id:
                continue
            if rec.get("consumedAt"):
                continue
            if int(rec.get("expiresAt") or 0) <= now:
                continue
            rec = dict(rec)
            rec["_path"] = str(path)
            records.append(rec)
    legacy = _read_preflight_record(root / _DISPATCH_PREFLIGHT_LEGACY)
    if legacy and legacy.get("agent") == agent_id and not legacy.get("consumedAt"):
        if int(legacy.get("expiresAt") or 0) > now:
            rec = dict(legacy)
            rec["_path"] = str(root / _DISPATCH_PREFLIGHT_LEGACY)
            records.append(rec)
    return records


def _consume_dispatch_preflight(root: Path, payload: dict[str, Any]) -> None:
    path_str = payload.get("_path")
    if not path_str:
        dispatch_id = str(payload.get("dispatchId") or "")
        if dispatch_id:
            path_str = str(root / _DISPATCH_PREFLIGHT_DIR / f"{dispatch_id}.json")
        else:
            path_str = str(root / _DISPATCH_PREFLIGHT_LEGACY)
    path = Path(path_str)
    clean = {k: v for k, v in payload.items() if k != "_path"}
    clean["consumedAt"] = int(time.time())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean, indent=2) + "\n", encoding="utf-8")


def _load_preflight_by_dispatch_id(root: Path, dispatch_id: str) -> dict[str, Any] | None:
    keyed = _read_preflight_record(root / _DISPATCH_PREFLIGHT_DIR / f"{dispatch_id}.json")
    if keyed:
        keyed = dict(keyed)
        keyed["_path"] = str(root / _DISPATCH_PREFLIGHT_DIR / f"{dispatch_id}.json")
        return keyed
    legacy = _read_preflight_record(root / _DISPATCH_PREFLIGHT_LEGACY)
    if legacy and str(legacy.get("dispatchId") or "") == dispatch_id:
        legacy = dict(legacy)
        legacy["_path"] = str(root / _DISPATCH_PREFLIGHT_LEGACY)
        return legacy
    return None


def validate_dispatch_preflight(
    root: Path,
    agent_id: str,
    dispatch_id: str | None = None,
) -> DispatchResult:
    if dispatch_id:
        preflight = _load_preflight_by_dispatch_id(root, dispatch_id)
        if not preflight:
            return DispatchResult(
                verdict="fail",
                agent=agent_id,
                dispatch_id=dispatch_id,
                cause="missing-preflight-nonce",
                remediation=(
                    "run dispatch preflight immediately before Task: "
                    "python3 scripts/wave.py dispatch preflight --dispatch-id <id> --agent <id>"
                ),
            )
    else:
        matches = _list_unconsumed_preflights(root, agent_id)
        if not matches:
            legacy = _read_preflight_record(root / _DISPATCH_PREFLIGHT_LEGACY)
            if legacy and legacy.get("agent") == agent_id:
                preflight = dict(legacy)
                preflight["_path"] = str(root / _DISPATCH_PREFLIGHT_LEGACY)
            else:
                return DispatchResult(
                    verdict="fail",
                    agent=agent_id,
                    cause="missing-preflight-nonce",
                    remediation=(
                        "run dispatch preflight immediately before Task: "
                        "python3 scripts/wave.py dispatch preflight --dispatch-id <id> --agent <id>"
                    ),
                )
        elif len(matches) == 1:
            preflight = matches[0]
        else:
            return DispatchResult(
                verdict="fail",
                agent=agent_id,
                cause="preflight-dispatch-ambiguous",
                remediation=(
                    "multiple unconsumed preflight records match agent; "
                    "set tool_input.metadata.dispatchId to the intended record id"
                ),
            )

    now = int(time.time())
    if preflight.get("consumedAt"):
        return DispatchResult(
            verdict="fail",
            agent=agent_id,
            cause="stale-preflight-nonce",
            remediation="dispatch preflight nonce already consumed; run a fresh preflight before Task",
        )
    if preflight.get("agent") != agent_id:
        return DispatchResult(
            verdict="fail",
            agent=agent_id,
            cause="preflight-agent-mismatch",
            remediation="dispatch preflight agent must match Task agent id",
        )
    expires_at = int(preflight.get("expiresAt") or 0)
    if expires_at <= now:
        return DispatchResult(
            verdict="fail",
            agent=agent_id,
            cause="stale-preflight-nonce",
            remediation="dispatch preflight expired; run preflight again immediately before Task",
        )
    intensity = str(preflight.get("intensity") or "")
    if intensity not in {"normal", "lite", "full", "ultra"}:
        return DispatchResult(
            verdict="fail",
            agent=agent_id,
            cause="binding:no-intensity",
            remediation="dispatch preflight record missing resolved intensity",
        )
    model_id = str(preflight.get("modelId") or "")
    if not model_id:
        return DispatchResult(
            verdict="fail",
            agent=agent_id,
            cause="binding:no-model",
            remediation="dispatch preflight record missing concrete model id",
        )
    cmd_raw = preflight.get("command")
    skill_raw = preflight.get("skill")
    command_name = str(cmd_raw) if isinstance(cmd_raw, str) and cmd_raw else None
    skill_name = str(skill_raw) if isinstance(skill_raw, str) and skill_raw else None
    _consume_dispatch_preflight(root, preflight)
    return DispatchResult(
        verdict="pass",
        agent=agent_id,
        model_id=model_id,
        tier=str(preflight.get("modelTier") or ""),
        intensity=intensity,
        dispatch_id=str(preflight.get("dispatchId") or dispatch_id or ""),
        command=command_name,
        skill=skill_name,
    )


def validate_memory_prework(root: Path) -> DispatchResult:
    cause = validate_fresh_record(load_record(root))
    if cause:
        return DispatchResult(
            verdict="fail",
            cause=cause,
            remediation=(
                "run pre-work memory search and record before the first file mutation: "
                "python3 scripts/wave.py memory prework record --surface <sw-command> "
                "[--scope paths] [--hit-count N]"
            ),
        )
    return DispatchResult(verdict="pass")


def evaluate_pre_tool_use(payload: dict[str, Any], root: Path) -> DispatchResult:
    tool_name = str(payload.get("tool_name") or "")

    if tool_name in _MUTATING_TOOL_NAMES:
        prework = validate_memory_prework(root)
        if prework.verdict != "pass":
            prework = DispatchResult(
                verdict="fail",
                cause=prework.cause,
                remediation=prework.remediation,
            )
            return prework
        consume_record(root)
        return DispatchResult(verdict="skip")

    if tool_name not in _TASK_TOOL_NAMES:
        return DispatchResult(verdict="skip")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return DispatchResult(verdict="skip")
    agent_id = agent_id_from_task_input(tool_input)
    if not agent_id or not is_bound_agent(agent_id):
        return DispatchResult(verdict="skip")
    dispatch_id = dispatch_id_from_task_input(tool_input)
    preflight = validate_dispatch_preflight(root, agent_id, dispatch_id)
    if preflight.verdict != "pass":
        return preflight
    resolved = resolve_dispatch_model(
        root,
        agent_id,
        command=preflight.command,
        skill=preflight.skill,
    )
    if resolved.verdict != "pass":
        return resolved
    if preflight.model_id and resolved.model_id and preflight.model_id != resolved.model_id:
        return DispatchResult(
            verdict="fail",
            agent=agent_id,
            cause="binding:model-mismatch",
            remediation="dispatch preflight model does not match current routing resolution; rerun preflight",
        )
    return DispatchResult(
        verdict="pass",
        agent=agent_id,
        model_id=preflight.model_id or resolved.model_id,
        tier=resolved.tier,
        intensity=preflight.intensity,
        dispatch_id=preflight.dispatch_id,
    )


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
