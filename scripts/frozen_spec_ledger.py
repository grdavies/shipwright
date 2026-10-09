#!/usr/bin/env python3
"""Frozen specification versus execution ledger helpers (PRD 081 R23)."""
from __future__ import annotations

import hashlib
import json
import re
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


def spec_is_frozen(
    text: str,
    *,
    root: Path | None = None,
    body_path: str | Path | None = None,
) -> bool:
    """Frontmatter freeze pin, or issue-store verify-frozen-hash (PRD 043)."""
    if is_frozen_task_list(text):
        return True
    if root is None or body_path is None:
        return False
    from planning_materialize import issue_store_frozen_verified

    return bool(issue_store_frozen_verified(root, str(body_path)))


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


def effective_task_checkboxes(
    text: str,
    ledger_tasks: dict[str, Any],
    *,
    frozen: bool | None = None,
    root: Path | None = None,
    body_path: str | Path | None = None,
) -> dict[str, bool]:
    """Ledger-backed checkbox truth for frozen specs; file parse otherwise (R23)."""
    file_boxes = parse_task_checkboxes(text)
    if frozen is None:
        frozen = spec_is_frozen(text, root=root, body_path=body_path)
    if not frozen:
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


def runtime_completion_valid(
    root: Path,
    state: dict[str, Any],
    text: str,
    task_ref: str,
    entry: dict[str, Any],
) -> bool:
    """Validate a captured native child receipt against current phase ownership.

    The durable ledger is trusted storage, like ordinary body-ref completion. An
    extra ref additionally needs a frozen-spec binding and corroborated native
    integration receipt; ``done`` or a synthetic flag alone never suffices.
    """
    from doc_format import phase_section_text

    proof = entry.get("runtimeCompletion")
    if not isinstance(proof, dict) or proof.get("version") != 1:
        return False
    if not state.get("runId") or proof.get("runId") != state["runId"]:
        return False
    if proof.get("taskList") != state.get("source_task_list"):
        return False
    if proof.get("bodyHash") != frozen_body_hash(text):
        return False
    phase_id = proof.get("phaseId")
    phase_slug = proof.get("phaseSlug")
    if not isinstance(phase_id, str) or not phase_id or not phase_slug:
        return False
    phases = state.get("phases")
    phase = phases.get(phase_id) if isinstance(phases, dict) else None
    if not isinstance(phase, dict) or phase.get("slug") != phase_slug or entry.get("phase") != phase_slug:
        return False
    ref, journal = proof.get("ref"), proof.get("integration")
    if not isinstance(ref, dict) or not isinstance(journal, dict):
        return False
    parent = ref.get("parentRef")
    phase_refs = parse_task_checkboxes(phase_section_text(text, phase_id))
    if not isinstance(parent, str) or parent not in phase_refs:
        return False
    if task_ref in parse_task_checkboxes(text) or not re.fullmatch(re.escape(parent) + r"\.[1-9][0-9]*", task_ref):
        return False
    if ref.get("id") != task_ref or ref.get("synthetic") is not True or ref.get("status") != "integrated":
        return False
    commit = ref.get("mergeCommit")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit):
        return False
    branch = ref.get("branch")
    if not isinstance(branch, str) or not branch or journal.get("sourceRef") != branch:
        return False
    if journal.get("taskRef") != task_ref or journal.get("verdict") != "pass" or journal.get("mergeCommit") != commit:
        return False
    if journal.get("conflicts") != []:
        return False
    # Resolve only in the caller's repository. A deleted phase branch is allowed
    # only after native phase merge persisted its immutable integration commit.
    anchor = phase.get("mergeCommit") or phase.get("branch")
    if not isinstance(anchor, str) or not anchor or anchor.startswith("-"):
        return False
    proc = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, anchor],
        cwd=root, capture_output=True, text=True, timeout=15,
    )
    return proc.returncode == 0


def capture_runtime_completion(
    root: Path,
    state: dict[str, Any],
    task_ref: str,
    phase_slug: str | None,
    run_dir: Path,
) -> dict[str, Any]:
    """Capture the latest exact native plan/journal pair or reject without writes."""
    task_list = state.get("source_task_list")
    if not isinstance(task_list, str) or not task_list:
        raise ValueError("runtime completion requires the state's source task list")
    task_path = root / task_list
    text = task_path.read_text(encoding="utf-8")
    if not spec_is_frozen(text, root=root, body_path=task_list):
        raise ValueError("runtime completion requires a frozen task list")
    plan_bytes = (run_dir / "execute-step-plan.json").read_bytes()
    journal_bytes = (run_dir / "integrate-journal.json").read_bytes()
    plan, journal = json.loads(plan_bytes), json.loads(journal_bytes)
    if not isinstance(plan, dict) or plan.get("version") != 1 or plan.get("tier") != "execute":
        raise ValueError("runtime completion requires a native execute plan")
    if not isinstance(journal, dict) or journal.get("version") != 1 or not isinstance(journal.get("entries"), list):
        raise ValueError("runtime completion requires a native integration journal")
    if not isinstance(plan.get("refs"), list):
        raise ValueError("runtime completion requires execute refs")
    refs = [r for r in plan["refs"] if isinstance(r, dict) and r.get("id") == task_ref]
    matches = [r for r in journal["entries"] if isinstance(r, dict) and r.get("taskRef") == task_ref]
    if len(refs) != 1 or not matches:
        raise ValueError("runtime completion requires one exact ref and its latest journal entry")
    proof = {
        "version": 1, "runId": state.get("runId"), "taskList": task_list,
        "bodyHash": frozen_body_hash(text), "phaseId": plan.get("phaseId"),
        "phaseSlug": plan.get("phaseSlug"),
        "ref": {k: refs[0].get(k) for k in ("id", "parentRef", "synthetic", "status", "branch", "mergeCommit")},
        "integration": {k: matches[-1].get(k) for k in ("taskRef", "sourceRef", "verdict", "mergeCommit", "conflicts", "at")},
        "planSha256": hashlib.sha256(plan_bytes).hexdigest(),
        "journalSha256": hashlib.sha256(journal_bytes).hexdigest(),
    }
    entry = {"phase": phase_slug, "runtimeCompletion": proof}
    if not runtime_completion_valid(root, state, text, task_ref, entry):
        raise ValueError("runtime completion evidence does not match frozen parent, phase, or native integration")
    return proof
