#!/usr/bin/env python3
"""Episodic orchestrator plan surfacing (PRD 024 R21)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from wave_json_io import write_json

PLAN_FILENAME = "orchestrator-step-plan.json"
SUMMARY_FILENAME = "episodic-run-summary.json"
REJECTIONS_FILENAME = "plan-rejections.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def plan_path(run_dir: Path) -> Path:
    return run_dir / PLAN_FILENAME


def summary_path(run_dir: Path) -> Path:
    return run_dir / SUMMARY_FILENAME


def read_summary(run_dir: Path) -> dict[str, Any]:
    path = summary_path(run_dir)
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def persist_validated_plan(run_dir: Path, plan: dict[str, Any]) -> Path:
    target = plan_path(run_dir)
    write_json(target, plan)
    return target


def surface_entry(
    run_dir: Path,
    *,
    orchestrator_type: str,
    run_id: str,
    plan_policy: str,
    chosen_plan: dict[str, Any] | None,
    capability_set: dict[str, Any] | None,
    plan_rejections: list[dict[str, Any]] | None = None,
) -> Path:
    payload = {
        "version": 1,
        "orchestratorType": orchestrator_type,
        "runId": run_id,
        "durability": "episodic",
        "planPolicy": plan_policy,
        "chosenPlan": chosen_plan,
        "capabilitySet": capability_set,
        "planRejections": plan_rejections or [],
        "writtenAt": utc_now(),
    }
    target = summary_path(run_dir)
    write_json(target, payload)
    return target


def append_rejection(run_dir: Path, rejection: dict[str, Any]) -> int:
    path = run_dir / REJECTIONS_FILENAME
    data: dict[str, Any] = {"rejections": []}
    if path.is_file():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data = loaded
    rejections = list(data.get("rejections") or [])
    rejections.append({**rejection, "at": utc_now()})
    data["rejections"] = rejections
    data["count"] = len(rejections)
    write_json(path, data)
    return len(rejections)
