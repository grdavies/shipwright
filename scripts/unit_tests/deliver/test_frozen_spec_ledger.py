"""Frozen specification versus execution ledger fixtures (PRD 081 R23)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from frozen_spec_ledger import (
    frozen_body_hash,
    is_frozen_task_list,
    project_checkboxes_from_ledger,
    reject_hashed_body_write,
    task_done_in_ledger,
)
from checkbox_diff import parse_task_checkboxes, toggle_checkbox


FROZEN_TASKS = """---
frozen: true
id: tasks-081-fixture
---
### 1. Alpha phase

- [ ] 1.1 First task
- [ ] 1.2 Second task
"""


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)


def _write_state(tmp_path: Path, payload: dict) -> Path:
    state_path = tmp_path / ".cursor" / "sw-deliver-state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return state_path


def test_frozen_hash_unchanged_after_ledger_progress(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    task_path = tmp_path / "docs" / "prds" / "081-fixture" / "tasks-081-fixture.md"
    task_path.parent.mkdir(parents=True)
    task_path.write_text(FROZEN_TASKS, encoding="utf-8")
    before_hash = frozen_body_hash(task_path.read_text(encoding="utf-8"))
    assert is_frozen_task_list(task_path.read_text(encoding="utf-8"))

    _write_state(
        tmp_path,
        {
            "verdict": "running",
            "source_task_list": "docs/prds/081-fixture/tasks-081-fixture.md",
            "taskLedger": {"tasks": {}, "phases": {}},
        },
    )
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_DIR / "wave_state.py"),
            str(tmp_path),
            "ledger",
            "record",
            "--task",
            "1.1",
            "--phase",
            "alpha",
            "--done",
            "true",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    after_hash = frozen_body_hash(task_path.read_text(encoding="utf-8"))
    assert before_hash == after_hash
    assert parse_task_checkboxes(task_path.read_text(encoding="utf-8"))["1.1"] is False


def test_checkbox_projection_reflects_ledger(tmp_path: Path) -> None:
    ledger_tasks = {
        "1.1": {"done": True, "phase": "alpha"},
        "1.2": {"done": False, "phase": "alpha"},
    }
    projected = project_checkboxes_from_ledger(FROZEN_TASKS, ledger_tasks)
    boxes = parse_task_checkboxes(projected)
    assert boxes["1.1"] is True
    assert boxes["1.2"] is False
    assert task_done_in_ledger(ledger_tasks, "1.1")
    assert not task_done_in_ledger(ledger_tasks, "1.2")


def test_direct_hashed_body_write_rejected() -> None:
    mutated = toggle_checkbox(FROZEN_TASKS, "1.1", done=True)
    rejected = reject_hashed_body_write(FROZEN_TASKS, mutated)
    assert rejected is not None
    assert rejected["error"] == "hashed-body-write-rejected"


def test_tasks_progress_toggle_records_ledger_not_body(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _init_repo(tmp_path)
    task_path = tmp_path / "docs" / "prds" / "081-fixture" / "tasks-081-fixture.md"
    task_path.parent.mkdir(parents=True)
    task_path.write_text(FROZEN_TASKS, encoding="utf-8")
    before_hash = frozen_body_hash(task_path.read_text(encoding="utf-8"))
    _write_state(
        tmp_path,
        {
            "verdict": "running",
            "source_task_list": "docs/prds/081-fixture/tasks-081-fixture.md",
            "taskLedger": {"tasks": {}, "phases": {}},
        },
    )
    monkeypatch.chdir(tmp_path)
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_DIR / "tasks-progress.py"),
            "toggle",
            "--file",
            str(task_path),
            "--ref",
            "1.1",
            "--done",
            "true",
            "--phase",
            "alpha",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["action"] == "ledger-toggle"
    assert parse_task_checkboxes(task_path.read_text(encoding="utf-8"))["1.1"] is False
    assert before_hash == frozen_body_hash(task_path.read_text(encoding="utf-8"))
    assert parse_task_checkboxes(payload["projected"])["1.1"] is True


def test_issue_store_progress_uses_ledger_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    _init_repo(tmp_path)
    (tmp_path / ".cursor" / "hooks" / "state").mkdir(parents=True)
    (tmp_path / ".cursor" / "workflow.config.json").write_text(
        json.dumps(
            {
                "version": 1,
                "planning": {
                    "store": {
                        "backend": "issue-store",
                        "issuesProvider": "github-issues",
                        "projectKey": "ledger-081",
                    }
                },
                "host": {"provider": "github"},
            }
        ),
        encoding="utf-8",
    )
    task_rel = "docs/prds/081-fixture/tasks-081-fixture.md"
    task_path = tmp_path / task_rel
    task_path.parent.mkdir(parents=True)
    task_path.write_text(FROZEN_TASKS, encoding="utf-8")
    before_hash = frozen_body_hash(task_path.read_text(encoding="utf-8"))

    import planning_progress as pp

    state = {
        "source_task_list": task_rel,
        "taskLedger": {"tasks": {"1.1": {"done": True, "phase": "alpha"}}, "phases": {}},
    }
    pp.provision_deliver_hierarchy(tmp_path, state)
    out = pp.sync_task_checkbox(tmp_path, state, phase_id="1", task_list=task_rel, task_ref="1.1")
    assert out.get("verdict") == "ok", out
    assert out.get("action") == "local-progress-write", out
    assert before_hash == frozen_body_hash(task_path.read_text(encoding="utf-8"))

    progress_path = Path(out["path"])
    assert progress_path.is_file(), out
    progress_doc = json.loads(progress_path.read_text(encoding="utf-8"))
    assert progress_doc.get("action") == "task-checkbox"
    assert progress_doc.get("taskRef") == "1.1"
    projected = project_checkboxes_from_ledger(
        task_path.read_text(encoding="utf-8"),
        state["taskLedger"]["tasks"],
    )
    assert parse_task_checkboxes(projected)["1.1"] is True
