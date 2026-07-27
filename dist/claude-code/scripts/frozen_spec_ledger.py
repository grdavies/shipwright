#!/usr/bin/env python3
"""Frozen specification versus execution ledger helpers (PRD 081 R23)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from checkbox_diff import parse_task_checkboxes, toggle_checkbox
from planning_materialize import parse_frontmatter
from planning_store import content_hash

SCRIPT_DIR = Path(__file__).resolve().parent


def is_frozen_task_list(text: str) -> bool:
    """True when frontmatter pins the body as frozen."""
    fm = parse_frontmatter(text)
    return fm.get("frozen", "").lower() == "true"


def frozen_body_hash(text: str) -> str:
    """Digest of the on-disk frozen body bytes (integrity witness)."""
    return content_hash(text)


def reject_hashed_body_write(old_text: str, new_text: str) -> dict[str, Any] | None:
    """Fail closed when a write would mutate a freeze-hashed specification body."""
    if not is_frozen_task_list(old_text):
        return None
    if old_text == new_text:
        return None
    return {
        "verdict": "fail",
        "error": "hashed-body-write-rejected",
        "reason": "record progress in the execution ledger, not the frozen body",
    }


def ledger_tasks_map(state: dict[str, Any] | None) -> dict[str, Any]:
    if not state:
        return {}
    ledger = state.get("taskLedger") or {}
    tasks = ledger.get("tasks") if isinstance(ledger, dict) else {}
    return tasks if isinstance(tasks, dict) else {}


def task_done_in_ledger(ledger_tasks: dict[str, Any], task_ref: str) -> bool:
    entry = ledger_tasks.get(task_ref)
    return bool(entry.get("done")) if isinstance(entry, dict) else False


def effective_task_checkboxes(text: str, ledger_tasks: dict[str, Any]) -> dict[str, bool]:
    """Ledger-backed checkbox truth for frozen specs; file parse otherwise (R23)."""
    file_boxes = parse_task_checkboxes(text)
    if not is_frozen_task_list(text):
        return file_boxes
    return {ref: task_done_in_ledger(ledger_tasks, ref) for ref in file_boxes}


def project_checkboxes_from_ledger(text: str, ledger_tasks: dict[str, Any]) -> str:
    """Derive checkbox rendering from the execution ledger without mutating frozen bytes."""
    if not is_frozen_task_list(text):
        return text
    projected = text
    for ref in parse_task_checkboxes(text):
        done = task_done_in_ledger(ledger_tasks, ref)
        try:
            projected = toggle_checkbox(projected, ref, done=done)
        except ValueError:
            continue
    return projected


def record_ledger_subtask(
    root: Path,
    task_ref: str,
    phase_slug: str,
    *,
    done: bool = True,
) -> dict[str, Any]:
    """Persist per-subtask progress in durable run-state execution ledger."""
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_DIR / "wave_state.py"),
            str(root),
            "ledger",
            "record",
            "--task",
            task_ref,
            "--phase",
            phase_slug,
            "--done",
            "true" if done else "false",
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        try:
            detail = json.loads(proc.stdout or proc.stderr or "{}")
        except json.JSONDecodeError:
            detail = {"verdict": "fail", "error": proc.stderr.strip() or proc.stdout.strip()}
        return detail
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"verdict": "pass", "action": "ledger-record", "task": task_ref, "done": done}
