"""Regression fixtures for planning-store rematerialize-with-resync (PRD 059 R9-R11)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.git]


def _load_planning_store(repo_root: Path):
    path = repo_root / "scripts" / "planning_store.py"
    spec = importlib.util.spec_from_file_location("planning_store", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    sys.path.insert(0, str(repo_root / "scripts"))
    spec.loader.exec_module(mod)
    return mod


def _load_wave_deliver(repo_root: Path):
    path = repo_root / "scripts" / "wave_deliver.py"
    spec = importlib.util.spec_from_file_location("wave_deliver", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    sys.path.insert(0, str(repo_root / "scripts"))
    spec.loader.exec_module(mod)
    return mod


def _write_tasks(path: Path, *, checked: set[str] | None = None) -> None:
    checked = checked or set()
    lines = [
        "---",
        "frozen: true",
        "---",
        "",
        "### 1. Resync fixture",
        "",
        f"- [{'x' if '1.1' in checked else ' '}] 1.1 First subtask",
        f"- [{'x' if '1.2' in checked else ' '}] 1.2 Second subtask",
        f"- [{'x' if '1.3' in checked else ' '}] 1.3 Third subtask",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def test_resync_recovers_ledger_recorded_progress(tmp_git_repo: Path, repo_root: Path) -> None:
    """Wiped local task list resynced against ledger recovers recorded progress (R9)."""
    ps = _load_planning_store(repo_root)
    task_rel = "docs/prds/099-resync/tasks-099-resync.md"
    src = tmp_git_repo / task_rel
    _write_tasks(src)
    dest = tmp_git_repo / ".cursor" / "planning-materialized" / task_rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    _write_tasks(dest, checked={"1.1", "1.3"})

    state = {
        "taskLedger": {
            "tasks": {
                "1.1": {"done": True},
                "1.2": {"done": True},
            }
        }
    }
    _write_tasks(dest)

    result = ps.materialize_with_resync(
        tmp_git_repo,
        "tasks-099-resync",
        task_rel,
        dest,
        state=state,
        task_list=task_rel,
    )
    assert result["verdict"] == "ok", result
    assert result["checksApplied"] >= 1
    body = dest.read_text(encoding="utf-8")
    assert "- [x] 1.1" in body
    assert "- [x] 1.2" in body


def test_resync_reports_local_only_checked_divergence(tmp_git_repo: Path, repo_root: Path) -> None:
    """Locally checked subtask absent from ledger is a divergence finding (R10)."""
    ps = _load_planning_store(repo_root)
    task_rel = "docs/prds/099-resync-div/tasks-099-resync-div.md"
    src = tmp_git_repo / task_rel
    _write_tasks(src)
    dest = tmp_git_repo / ".cursor" / "planning-materialized" / task_rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    _write_tasks(dest, checked={"1.3"})

    state = {"taskLedger": {"tasks": {"1.1": {"done": True}}}}
    result = ps.materialize_with_resync(
        tmp_git_repo,
        "tasks-099-resync-div",
        task_rel,
        dest,
        state=state,
        task_list=task_rel,
    )
    assert result["verdict"] == "fail"
    assert "1.3" in (result.get("divergences") or [])
    assert result.get("error") == "local-checked-but-ledger-unchecked"


def test_resync_auto_invocation_blocked_during_merge_or_terminal(repo_root: Path) -> None:
    """Auto-resync guard does not fire while merge or terminal work is in-flight (R11)."""
    wd = _load_wave_deliver(repo_root)
    assert wd.resync_auto_invocation_blocked({"mergeJournal": {"phase": "3"}})
    assert wd.resync_auto_invocation_blocked({"nextAction": "terminal"})
    assert wd.resync_auto_invocation_blocked(
        {"terminalShip": {"status": "watching"}}
    )
    assert not wd.resync_auto_invocation_blocked({"nextAction": "phase-dispatch"})
