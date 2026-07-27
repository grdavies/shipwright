#!/usr/bin/env python3
"""Per-task execute status writer (TDD + refactor rollup, PRD 039 R2)."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from _sw.cli import run_module_main
from frozen_spec_ledger import record_ledger_subtask, reject_hashed_body_write


def sanitize_ref(task_ref: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", task_ref).strip("-") or "unknown"


def status_path(root: Path, task_ref: str) -> Path:
    return root / ".cursor" / "sw-execute-runs" / sanitize_ref(task_ref) / "status.json"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--task-ref", required=True)
    p.add_argument("--write", default="")
    p.add_argument("--read", action="store_true")
    ns = p.parse_args(list(sys.argv[1:] if argv is None else argv))
    root = Path.cwd()
    path = status_path(root, ns.task_ref)
    if ns.read:
        if not path.is_file():
            print(json.dumps({"verdict": "missing", "taskRef": ns.task_ref}))
            return 2
        print(path.read_text(encoding="utf-8"))
        return 0
    if not ns.write:
        print("Usage: execute_task_status.py --task-ref REF --write '{...}'", file=sys.stderr)
        return 2
    data = json.loads(ns.write)
    data.setdefault("taskRef", ns.task_ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    verdict = str(data.get("verdict") or "")
    task_list = os.environ.get("SW_TASK_LIST", "")
    phase_slug = os.environ.get("SW_PHASE_SLUG", "")
    if verdict in ("green", "pass") and task_list and phase_slug:
        tasks_path = Path(task_list)
        if not tasks_path.is_absolute():
            tasks_path = (root / task_list).resolve()
        if tasks_path.is_file():
            old_text = tasks_path.read_text(encoding="utf-8")
            rejected = reject_hashed_body_write(old_text, old_text)
            if rejected:
                print(json.dumps(rejected))
                return 1
        ledger_out = record_ledger_subtask(root, ns.task_ref, phase_slug, done=True)
        if ledger_out.get("verdict") not in ("pass", "ok"):
            print(json.dumps(ledger_out))
            return 1
        from planning_progress import propagate_checkbox_to_issue_store

        issue_sync = propagate_checkbox_to_issue_store(root, ns.task_ref, task_list, phase_slug)
        status_out = {"verdict": "pass", "path": str(path), "ledger": ledger_out}
        if issue_sync.get("synced") or issue_sync.get("degraded"):
            status_out["issueSync"] = issue_sync
        print(json.dumps(status_out))
        return 0
    print(json.dumps({"verdict": "pass", "path": str(path)}))
    return 0


if __name__ == "__main__":
    run_module_main(main)
