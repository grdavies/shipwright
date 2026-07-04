#!/usr/bin/env python3
"""Deliver-scoped plan surfacing for run.log and consolidated reports (PRD 023 R21)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from plan_persist import PHASE_PLAN_FILENAME
from wave_plan_validate import PLAN_REJECTION_LOG_KEY

REPORT_KIND_HALT = "halt"
REPORT_KIND_TERMINAL = "terminal"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def deliver_run_log_path(root: Path, target: str | None = None, state: dict | None = None) -> Path:
    from wave_state import deliver_run_log_path as _path
    return _path(root, target=target, state=state)


def phase_run_dir(root: Path, slug: str) -> Path:
    return root / ".cursor" / "sw-deliver-runs" / slug


def append_run_log(root: Path, entry: dict[str, Any], *, state: dict[str, Any] | None = None) -> None:
    log_path = deliver_run_log_path(root, state=state)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({**entry, "at": utc_now()}, ensure_ascii=False) + "\n"
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(line)
    os.chmod(log_path, 0o600)


def read_run_log_events(root: Path, event: str | None = None, *, state: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    log_path = deliver_run_log_path(root, state=state)
    if not log_path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        if event is None or row.get("event") == event:
            rows.append(row)
    return rows


def collect_wave_plan(state: dict[str, Any]) -> dict[str, Any] | None:
    plan = state.get("waveBatchingPlan")
    if not isinstance(plan, dict):
        return None
    return {
        "planPolicy": plan.get("planPolicy"),
        "waves": plan.get("waves"),
        "parallelCeiling": plan.get("parallelCeiling"),
        "fallback": plan.get("fallback"),
        "validatedAt": plan.get("validatedAt"),
    }


def collect_phase_step_plans(root: Path, state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    plans: dict[str, dict[str, Any]] = {}
    for pid, meta in (state.get("phases") or {}).items():
        if not isinstance(meta, dict):
            continue
        slug = str(meta.get("slug") or pid)
        path = phase_run_dir(root, slug) / PHASE_PLAN_FILENAME
        data = read_json(path)
        if not data:
            continue
        plans[slug] = {
            "phaseId": pid,
            "steps": data.get("steps"),
            "planPolicy": data.get("planPolicy"),
            "phaseType": data.get("phaseType"),
            "fallback": data.get("fallback"),
            "validatedAt": data.get("validatedAt"),
        }
    return plans


def collect_plan_rejections(state: dict[str, Any]) -> dict[str, Any]:
    log = state.get(PLAN_REJECTION_LOG_KEY)
    if not isinstance(log, dict):
        return {"version": 1, "threshold": 3, "phases": {}, "halt": None, "rejections": []}

    rejections: list[dict[str, Any]] = []
    for phase_id, meta in (log.get("phases") or {}).items():
        if not isinstance(meta, dict):
            continue
        for entry in meta.get("entries") or []:
            if not isinstance(entry, dict):
                continue
            rejections.append(
                {
                    "phaseId": phase_id,
                    "verdict": entry.get("verdict"),
                    "tier": entry.get("tier"),
                    "reasons": list(entry.get("reasons") or []),
                    "at": entry.get("at"),
                }
            )

    return {
        "version": log.get("version", 1),
        "threshold": log.get("threshold", 3),
        "halt": log.get("halt"),
        "phases": log.get("phases") or {},
        "rejections": rejections,
    }


def collect_resolved_capabilities(root: Path, state: dict[str, Any]) -> list[dict[str, Any]]:
    slug_by_type: dict[str, str] = {}
    for pid, meta in (state.get("phases") or {}).items():
        if not isinstance(meta, dict):
            continue
        phase_type = meta.get("phaseType") or meta.get("type")
        slug = str(meta.get("slug") or pid)
        if phase_type:
            slug_by_type[str(phase_type)] = slug

    rows: list[dict[str, Any]] = []
    for entry in read_run_log_events(root, "capability-selection", state=state):
        phase_slug = entry.get("phaseSlug")
        phase_type = entry.get("phaseType")
        if not phase_slug and phase_type:
            phase_slug = slug_by_type.get(str(phase_type))
        rows.append(
            {
                "phaseSlug": phase_slug,
                "phaseType": phase_type,
                "resolvedCapabilities": list(entry.get("resolvedCapabilities") or []),
                "inputsHash": entry.get("inputsHash"),
                "membershipHash": entry.get("membershipHash"),
                "at": entry.get("at"),
            }
        )
    return rows


def build_plan_surfacing_snapshot(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    return {
        "waveBatchingPlan": collect_wave_plan(state),
        "phaseStepPlans": collect_phase_step_plans(root, state),
        "planRejections": collect_plan_rejections(state),
        "resolvedCapabilities": collect_resolved_capabilities(root, state),
    }


def surface_wave_plan_chosen(root: Path, wave_plan: dict[str, Any]) -> None:
    append_run_log(
        root,
        {
            "event": "wave-plan-chosen",
            "planPolicy": wave_plan.get("planPolicy"),
            "waves": wave_plan.get("waves"),
            "parallelCeiling": wave_plan.get("parallelCeiling"),
            "fallback": wave_plan.get("fallback"),
        },
    )


def surface_phase_plan_chosen(
    root: Path,
    *,
    phase_id: str,
    phase_slug: str,
    phase_plan: dict[str, Any],
) -> None:
    append_run_log(
        root,
        {
            "event": "phase-plan-chosen",
            "phaseId": phase_id,
            "phaseSlug": phase_slug,
            "steps": phase_plan.get("steps"),
            "planPolicy": phase_plan.get("planPolicy"),
            "phaseType": phase_plan.get("phaseType"),
            "fallback": phase_plan.get("fallback"),
        },
    )


def attach_plan_surfacing_to_report(
    root: Path,
    state: dict[str, Any],
    report: dict[str, Any],
    *,
    report_kind: str,
) -> dict[str, Any]:
    snapshot = build_plan_surfacing_snapshot(root, state)
    append_run_log(
        root,
        {
            "event": "deliver-plan-surfacing",
            "reportKind": report_kind,
            "snapshot": snapshot,
        },
        state=state,
    )
    report["planSurfacing"] = snapshot
    return report
