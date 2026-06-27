#!/usr/bin/env python3
"""Run-log surfacing for capability selection (PRD 021 R21, TR7)."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def inputs_hash(ctx: dict[str, Any]) -> str:
    payload = json.dumps(ctx, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def persona_short_name(capability_id: str) -> str:
    return capability_id.replace("persona.sw-", "").replace("-reviewer", "")


def build_activation_record(ctx: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Mirror doc-review activation record shape for auditability (R21)."""
    overrides = ctx.get("overrides") or {}
    if overrides.get("all"):
        override = "all"
    elif overrides.get("personas"):
        override = f"personas {', '.join(str(p) for p in overrides['personas'])}"
    else:
        override = "none"

    core: list[str] = []
    gated: list[dict[str, str]] = []

    for row in rows:
        if row.get("kind") != "persona":
            continue
        short = persona_short_name(str(row["id"]))
        triggers = [str(t) for t in row.get("matchedTriggers") or []]
        if "always_on" in triggers or any(t.startswith("override:") for t in triggers):
            core.append(short)
            continue
        if triggers:
            matched = next(
                (t for t in triggers if t not in {"always_on", "phase_default"}),
                triggers[0],
            )
            gated.append({"persona": short, "matched": matched})

    return {
        "core": sorted(set(core)),
        "gated": gated,
        "override": override,
    }


def build_log_entry(ctx: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    rows = result.get("capabilities") or []
    return {
        "event": "capability-selection",
        "inputsHash": inputs_hash(ctx),
        "membershipHash": result.get("membershipHash"),
        "resolvedCapabilities": [row["id"] for row in rows],
        "precedenceTrace": result.get("precedenceTrace"),
        "activationRecord": build_activation_record(ctx, rows),
        "phaseType": ctx.get("phase_type"),
    }


def append_run_log(path: Path, entry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({**entry, "at": utc_now()}, ensure_ascii=False) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
    os.chmod(path, 0o600)


def surface_capability_selection(
    root: Path,
    run_dir: Path | None,
    ctx: dict[str, Any],
    result: dict[str, Any],
) -> None:
    """Write selection audit record to deliver run.log and per-phase run-dir sink."""
    entry = build_log_entry(ctx, result)
    deliver_log = root / ".cursor" / "sw-deliver-runs" / "run.log"
    append_run_log(deliver_log, entry)
    if run_dir is not None:
        append_run_log(run_dir / "run.log", entry)
