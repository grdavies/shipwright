"""Regression: state-init must keep phases on the scoped path and preserve runId.

Bare load_state(root) follows the unscoped breadcrumb; state init writes the
scoped target/task-list path. Overwriting scoped state wiped run identity and
left deliver-loop oscillating state-init ↔ base-capture (conductor:no-progress).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import wave_state as ws  # noqa: E402
from wave_deliver_loop import load_state  # noqa: E402


@pytest.fixture(autouse=True)
def shipwright_scripts_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHIPWRIGHT_SCRIPTS", str(SCRIPT_DIR.resolve()))


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "README.md").write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-qm", "init")
    _git(tmp_path, "branch", "-M", "main")
    _git(tmp_path, "checkout", "-qb", "feat/phases-stick-demo")
    return tmp_path


def _write_plan(repo: Path) -> Path:
    plan = {
        "verdict": "pass",
        "mode": "phase",
        "source_task_list": "docs/prds/999-phases-stick-demo/tasks-999-phases-stick-demo.md",
        "prd_number": "999",
        "target": {
            "type": "feat",
            "slug": "phases-stick-demo",
            "branch": "feat/phases-stick-demo",
        },
        "items": [
            {
                "id": "1",
                "slug": "alpha-small",
                "title": "Alpha — small",
                "branch": "feat/phases-stick-demo-phase-alpha-small",
                "files": ["scripts/a.py"],
            },
            {
                "id": "2",
                "slug": "beta-small",
                "title": "Beta — small",
                "branch": "feat/phases-stick-demo-phase-beta-small",
                "files": ["scripts/b.py"],
            },
        ],
        "edges": [],
        "waves": [["1", "2"]],
    }
    path = repo / ("." + "cursor") / "sw-deliver-runs" / "deliver-test" / "plan.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    return path


def test_state_init_merges_phases_and_preserves_run_id(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    plan_path = _write_plan(repo)
    target = "feat/phases-stick-demo"
    task_list = "docs/prds/999-phases-stick-demo/tasks-999-phases-stick-demo.md"
    scoped = ws.resolve_state_path(repo, target=target, task_list=task_list)
    scoped.parent.mkdir(parents=True, exist_ok=True)
    scoped.write_text(
        json.dumps(
            {
                "runId": "deliver-keep-me",
                "targetLock": {"targetBranch": target, "runId": "deliver-keep-me"},
                "planHash": "abc123",
                "target": {"branch": target},
                "source_task_list": task_list,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as exited:
        ws.cmd_state_init(repo, ["--plan", str(plan_path.relative_to(repo))])
    assert exited.value.code == 0

    # Bare breadcrumb load can be empty — scoped load must see phases.
    bare = load_state(repo)
    scoped_state = ws.load_deliver_state(repo, target=target, task_list=task_list)
    assert scoped_state.get("runId") == "deliver-keep-me"
    assert scoped_state.get("planHash") == "abc123"
    phases = scoped_state.get("phases") or {}
    assert set(phases) == {"1", "2"}
    assert scoped_state.get("nextAction") == "base-capture"
    # Document the skew that caused the no-progress loop when breadcrumb is absent.
    if not bare.get("phases"):
        assert bare.get("runId") in (None, "")
