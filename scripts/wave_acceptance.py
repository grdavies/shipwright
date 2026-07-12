#!/usr/bin/env python3
"""Terminal acceptance record builder + validator for deliver runs (PRD 065 R14, R24, R30)."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from halt_resume import resolve_run_id
from wave_json_io import write_json

ACCEPTANCE_FILENAME = "terminal-acceptance.json"
TERMINAL_MERGED_STATUSES = frozenset(
    {"green-merged", "teardown-pending", "teardown-complete"}
)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def acceptance_record_path(root: Path) -> Path:
    return root / ".cursor" / "sw-deliver-runs" / ACCEPTANCE_FILENAME


def is_deliver_run(state: dict[str, Any]) -> bool:
    return bool(state.get("source_task_list"))


def interaction_count(state: dict[str, Any]) -> int:
    return int(state.get("legitimateHaltCount") or 0)


def gates_run_rollup(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    from merge_ready_enforcement import evaluate_mandatory_gate_evidence, mandatory_gate_ids

    phases: dict[str, Any] = {}
    mandatory_count = len(mandatory_gate_ids(root))
    for record in state.get("mergedPhases") or []:
        if not isinstance(record, dict):
            continue
        slug = str(record.get("phaseSlug") or "")
        if not slug:
            continue
        evaluation = evaluate_mandatory_gate_evidence(root, slug)
        phases[slug] = {
            "verdict": evaluation.get("verdict"),
            "mandatoryGateCount": mandatory_count,
            "failures": evaluation.get("failures") or [],
        }
    return {"phases": phases, "mandatoryGateCount": mandatory_count}


def build_phase_entries(state: dict[str, Any]) -> list[dict[str, Any]]:
    phase_meta = state.get("phases") or {}
    entries: list[dict[str, Any]] = []
    for record in state.get("mergedPhases") or []:
        if not isinstance(record, dict):
            continue
        pid = str(record.get("phaseId") or "")
        slug = str(record.get("phaseSlug") or "")
        meta = phase_meta.get(pid) if pid else {}
        if not isinstance(meta, dict):
            meta = {}
        entries.append(
            {
                "phaseId": pid,
                "phaseSlug": slug,
                "mergeState": str(meta.get("status") or "green-merged"),
                "mergeCommit": record.get("mergeCommit"),
                "mergedAt": record.get("mergedAt"),
                "pr": record.get("pr"),
            }
        )
    return entries


def build_acceptance_record(
    root: Path,
    state: dict[str, Any],
    *,
    terminal_gate: dict[str, Any] | None = None,
    gate_exit_code: int | None = None,
) -> dict[str, Any]:
    terminal = state.get("terminalPr") or {}
    return {
        "schemaVersion": 1,
        "recordedAt": utc_now(),
        "runId": resolve_run_id(state),
        "targetBranch": (state.get("target") or {}).get("branch"),
        "sourceTaskList": state.get("source_task_list"),
        "phases": build_phase_entries(state),
        "terminalPr": terminal if isinstance(terminal, dict) else {},
        "terminalGate": terminal_gate or {},
        "terminalGateExitCode": gate_exit_code,
        "gatesRunRollup": gates_run_rollup(root, state),
        "interactionCount": interaction_count(state),
    }


def validate_acceptance_record(
    root: Path,
    record: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    errors: list[str] = []
    if not is_deliver_run(state):
        return {"verdict": "skip", "reason": "not-a-deliver-run", "errors": []}

    phases = state.get("phases") or {}
    for pid, meta in phases.items():
        if not isinstance(meta, dict):
            continue
        status = str(meta.get("status") or "")
        if status in ("blocked", "rejected"):
            errors.append(f"phase-{pid}:blocked")
        elif status in ("pending", "in-flight"):
            errors.append(f"phase-{pid}:unmerged:{status}")

    terminal = record.get("terminalPr") or {}
    if isinstance(terminal, dict) and terminal.get("number") is not None:
        gate = record.get("terminalGate") or {}
        if str(gate.get("verdict") or "") != "green":
            errors.append(f"terminal-gate:not-green:{gate.get('verdict') or 'missing'}")
        exit_code = record.get("terminalGateExitCode")
        if exit_code not in (None, 0):
            errors.append(f"terminal-gate:exit-code:{exit_code}")

    rollup = record.get("gatesRunRollup") or {}
    phase_rollups = rollup.get("phases") if isinstance(rollup, dict) else {}
    if isinstance(phase_rollups, dict):
        for slug, summary in phase_rollups.items():
            if isinstance(summary, dict) and summary.get("verdict") != "pass":
                errors.append(f"gates-run:{slug}:{summary.get('verdict')}")

    verdict = "pass" if not errors else "fail"
    return {"verdict": verdict, "errors": errors}


def write_acceptance_record(
    root: Path,
    state: dict[str, Any],
    *,
    terminal_gate: dict[str, Any] | None = None,
    gate_exit_code: int | None = None,
) -> Path | None:
    if not is_deliver_run(state):
        return None
    record = build_acceptance_record(
        root,
        state,
        terminal_gate=terminal_gate,
        gate_exit_code=gate_exit_code,
    )
    path = acceptance_record_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, record)
    return path


def embed_validated_acceptance(
    root: Path,
    state: dict[str, Any],
    report: dict[str, Any],
    *,
    terminal_gate: dict[str, Any] | None = None,
    gate_exit_code: int | None = None,
) -> dict[str, Any]:
    if not is_deliver_run(state):
        report["terminalAcceptance"] = {"verdict": "skip", "reason": "interactive-or-non-deliver"}
        return report
    record = build_acceptance_record(
        root,
        state,
        terminal_gate=terminal_gate,
        gate_exit_code=gate_exit_code,
    )
    validation = validate_acceptance_record(root, record, state)
    report["terminalAcceptance"] = {"record": record, "validation": validation}
    path = acceptance_record_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, record)
    report["terminalAcceptancePath"] = str(path)
    return report
