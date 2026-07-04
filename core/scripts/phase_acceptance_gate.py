#!/usr/bin/env python3
"""Mechanical phase acceptance gate before deliver merge-enqueue (PRD 055 R11, R14)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import doc_format
from checkbox_diff import parse_task_checkboxes, toggle_checkbox

GAP_CAUSE_OPEN_REFS = "phase-acceptance:open-subtasks"
GAP_CAUSE_ALL_OPEN = "phase-acceptance:all-open-silent-partial"


def _task_list_from(state: dict[str, Any], plan: dict[str, Any] | None) -> str | None:
    raw = state.get("source_task_list")
    if not raw and plan:
        raw = plan.get("source_task_list")
    return str(raw) if raw else None


def resolve_tasks_path(
    root: Path, state: dict[str, Any], plan: dict[str, Any] | None
) -> tuple[Path, Path] | tuple[None, None]:
    """Return (check_root, tasks_path) or (None, None) when no frozen task list."""
    raw = _task_list_from(state, plan)
    if not raw:
        return None, None
    rel = str(raw)
    candidates = [root]
    orch = state.get("orchestratorWorktree") or {}
    wt_raw = orch.get("path")
    if wt_raw:
        orch_path = Path(str(wt_raw))
        if orch_path.is_dir():
            candidates.append(orch_path)
    for check_root in candidates:
        task_path = Path(rel)
        if not task_path.is_absolute():
            task_path = (check_root / rel).resolve()
        if task_path.is_file():
            return check_root, task_path
    return None, None


def phase_id_for_slug(text: str, phase_slug: str) -> str | None:
    for phase in doc_format.extract_phases(text):
        if phase.get("slug") == phase_slug:
            return str(phase.get("id") or "")
    return None


def phase_refs_checked(text: str, phase_id: str) -> dict[str, bool]:
    chunk = doc_format.phase_section_text(text, phase_id)
    if not chunk:
        return {}
    return parse_task_checkboxes(chunk)


def _phase_ledger_entry(state: dict[str, Any], phase_slug: str) -> dict[str, Any]:
    ledger = state.get("taskLedger") or {}
    phases = ledger.get("phases") if isinstance(ledger, dict) else {}
    if not isinstance(phases, dict):
        return {}
    entry = phases.get(phase_slug)
    return entry if isinstance(entry, dict) else {}


def _ledger_tasks(state: dict[str, Any]) -> dict[str, Any]:
    ledger = state.get("taskLedger") or {}
    tasks = ledger.get("tasks") if isinstance(ledger, dict) else {}
    return tasks if isinstance(tasks, dict) else {}


def check_phase_acceptance(
    root: Path,
    state: dict[str, Any],
    plan: dict[str, Any] | None,
    phase_id: str,
    phase_slug: str,
) -> tuple[bool, str | None]:
    """Verify phase sub-task refs are ledger done + checkbox toggled (R11)."""
    resolved = resolve_tasks_path(root, state, plan)
    if resolved == (None, None):
        return True, None
    _check_root, tasks_path = resolved
    text = tasks_path.read_text(encoding="utf-8")
    refs = phase_refs_checked(text, phase_id)
    if not refs:
        return True, None

    ledger_tasks = _ledger_tasks(state)
    phase_entry = _phase_ledger_entry(state, phase_slug)
    declared_partial = bool(phase_entry.get("declaredPartial"))
    skipped_raw = phase_entry.get("skippedRefs") or []
    skipped = {str(r) for r in skipped_raw} if isinstance(skipped_raw, list) else set()

    open_refs: list[str] = []
    for ref, checked in refs.items():
        if ref in skipped:
            continue
        entry = ledger_tasks.get(ref)
        ledger_done = bool(entry.get("done")) if isinstance(entry, dict) else False
        if checked and ledger_done:
            continue
        open_refs.append(ref)

    if not open_refs:
        return True, None

    all_unchecked = all(not checked for checked in refs.values())
    any_ledger_done = any(
        isinstance(ledger_tasks.get(ref), dict) and ledger_tasks[ref].get("done")
        for ref in refs
    )
    if all_unchecked and not any_ledger_done and not declared_partial:
        return False, GAP_CAUSE_ALL_OPEN

    return False, GAP_CAUSE_OPEN_REFS


def record_ref_completion(
    root: Path,
    task_ref: str,
    task_list: str,
    phase_slug: str,
) -> dict[str, Any]:
    """Auto ledger record + checkbox toggle on execute ref terminal green (R14)."""
    tasks_path = Path(task_list)
    if not tasks_path.is_absolute():
        tasks_path = (root / task_list).resolve()
    if not tasks_path.is_file():
        return {"verdict": "fail", "error": f"task file not found: {task_list}"}

    text = tasks_path.read_text(encoding="utf-8")
    try:
        new_text = toggle_checkbox(text, task_ref, done=True)
    except ValueError as exc:
        return {"verdict": "fail", "error": str(exc)}
    tasks_path.write_text(new_text, encoding="utf-8")

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
            "true",
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        try:
            detail = json.loads(proc.stdout or proc.stderr or "{}")
        except json.JSONDecodeError:
            detail = {"error": proc.stderr.strip() or proc.stdout.strip()}
        return {"verdict": "fail", "action": "ledger-record", **detail}
    return {"verdict": "pass", "action": "record-ref-completion", "task": task_ref}


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Phase acceptance gate (PRD 055 R11)")
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--phase-id", required=True)
    parser.add_argument("--phase-slug", required=True)
    parser.add_argument("--state-file", default="")
    parser.add_argument("--plan-file", default="")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    state: dict[str, Any] = {}
    plan: dict[str, Any] | None = None
    if args.state_file:
        state = json.loads(Path(args.state_file).read_text(encoding="utf-8"))
    elif (root / ".cursor" / "sw-deliver-state.json").is_file():
        state = json.loads((root / ".cursor" / "sw-deliver-state.json").read_text(encoding="utf-8"))
    if args.plan_file:
        plan = json.loads(Path(args.plan_file).read_text(encoding="utf-8"))

    ok, cause = check_phase_acceptance(
        root, state, plan, args.phase_id, args.phase_slug
    )
    if ok:
        print(json.dumps({"verdict": "pass", "action": "phase-acceptance"}))
        return 0
    print(json.dumps({"verdict": "fail", "error": cause or GAP_CAUSE_OPEN_REFS}))
    return 1


if __name__ == "__main__":
    from _sw.cli import run_module_main

    run_module_main(main)
