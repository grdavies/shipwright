#!/usr/bin/env python3
"""Entry-time signal_context capture for orchestrator plan-policy adoption (PRD 024 TR3)."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from orchestrator_step_plan import VALID_ORCHESTRATOR_TYPES

EPISODIC_OWNERS = frozenset({"debug", "feedback"})
REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "debug": ("signal_type",),
    "doc": ("tier", "doc_path"),
    "feedback": ("source_class", "invocation"),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def parse_kv(args: list[str], flag: str, default: str | None = None) -> str | None:
    if flag in args:
        i = args.index(flag)
        return args[i + 1] if i + 1 < len(args) else default
    return default


def owner_for(orchestrator_type: str) -> str:
    if orchestrator_type in EPISODIC_OWNERS:
        return "session/ephemeral"
    return "durable/docs-worktree"


def normalize_inputs(orchestrator_type: str, raw: dict[str, Any]) -> dict[str, Any]:
    ctx: dict[str, Any] = {"version": 1, "orchestrator_type": orchestrator_type}
    ctx["owner"] = owner_for(orchestrator_type)
    if orchestrator_type == "debug":
        for key in ("signal_type", "related_files", "sentry_ref"):
            if key in raw and raw[key] is not None:
                ctx[key] = raw[key]
    elif orchestrator_type == "doc":
        for key in ("tier", "doc_path", "file_paths", "derived_tags"):
            if key in raw and raw[key] is not None:
                ctx[key] = raw[key]
    elif orchestrator_type == "feedback":
        for key in ("source_class", "invocation", "route"):
            if key in raw and raw[key] is not None:
                ctx[key] = raw[key]
    return ctx


def validate_capture(orchestrator_type: str, ctx: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if orchestrator_type not in VALID_ORCHESTRATOR_TYPES:
        reasons.append(f"unknown orchestrator type: {orchestrator_type!r}")
        return reasons
    for field in REQUIRED_FIELDS.get(orchestrator_type, ()):
        value = ctx.get(field)
        if value is None or value == "" or value == []:
            reasons.append(f"signal_context.{field} required for {orchestrator_type}")
    if orchestrator_type == "debug":
        related = ctx.get("related_files")
        if related is not None and not isinstance(related, list):
            reasons.append("signal_context.related_files must be an array when present")
    return reasons


def capture(orchestrator_type: str, raw: dict[str, Any]) -> dict[str, Any]:
    ctx = normalize_inputs(orchestrator_type, raw)
    reasons = validate_capture(orchestrator_type, ctx)
    if reasons:
        return {"verdict": "reject", "reasons": reasons}
    ctx["capturedAt"] = utc_now()
    return {"verdict": "pass", "signal_context": ctx}


def load_json_arg(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    path = Path(raw)
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = json.loads(raw)
    return data if isinstance(data, dict) else {}


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in {"-h", "--help"}:
        emit(
            {
                "usage": "orchestrator_signal_context.py <repo> capture --orchestrator-type <debug|doc|feedback> [--input <json>]",
            }
        )
    root = Path(args[0]).resolve()
    cmd = args[1]
    if cmd != "capture":
        fail(f"unknown command: {cmd!r}")
    orchestrator_type = parse_kv(args[2:], "--orchestrator-type")
    if not orchestrator_type:
        fail("--orchestrator-type required")
    raw = load_json_arg(parse_kv(args[2:], "--input"))
    result = capture(orchestrator_type, raw)
    if result["verdict"] != "pass":
        emit(result, exit_code=20)
    from orchestrator_run import persist_signal_context  # noqa: PLC0415

    run_id = parse_kv(args[2:], "--run-id") or "entry"
    path = persist_signal_context(root, orchestrator_type, run_id, result["signal_context"])
    emit(
        {
            **result,
            "path": str(path.relative_to(root)),
            "snapshotPoint": "before-plan-validate",
        }
    )


if __name__ == "__main__":
    main()
