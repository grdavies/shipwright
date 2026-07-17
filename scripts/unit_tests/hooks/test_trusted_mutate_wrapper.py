"""Trusted mutation wrapper + Shell cutover fixtures (PRD 072 R8, KD7)."""
from __future__ import annotations

import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "core" / "hooks"))

from before_task_dispatch import evaluate_pre_tool_use  # noqa: E402
from memory_prework_gate import (  # noqa: E402
    DEFAULT_SURFACE_MUTATION_BUDGET,
    load_record,
    validate_fresh_record,
)
from sw_mutate import (  # noqa: E402
    cmd_apply,
    shell_tracked_mutation_cause,
    validate_prework_for_mutation,
)


def _git(cmd: list[str], cwd: Path) -> None:
    subprocess.run(["git", *cmd], cwd=str(cwd), check=True, capture_output=True, text=True)


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-q"], repo)
    _git(["config", "user.email", "t@t.com"], repo)
    _git(["config", "user.name", "t"], repo)
    (repo / "tracked.py").write_text("old\n", encoding="utf-8")
    _git(["add", "tracked.py"], repo)
    _git(["commit", "-q", "-m", "init"], repo)
    return repo


def _write_prework(repo: Path, *, budget: int = DEFAULT_SURFACE_MUTATION_BUDGET) -> None:
    now = int(time.time())
    record = {
        "surface": "sw-execute",
        "outcome": "memory:offline",
        "nonce": uuid.uuid4().hex,
        "createdAt": now,
        "expiresAt": now + 3600,
        "mutationBudget": budget,
        "mutationsUsed": 0,
    }
    state = repo / ".cursor" / "hooks" / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "memory-prework-search.json").write_text(
        json.dumps(record, indent=2) + "\n",
        encoding="utf-8",
    )


def test_wrapper_requires_fresh_prework(git_repo: Path) -> None:
    result = validate_prework_for_mutation(git_repo)
    assert result.verdict == "fail"
    assert result.cause == "missing-prework-search-record"


def test_wrapper_applies_write_with_fresh_prework(git_repo: Path) -> None:
    _write_prework(git_repo)
    outcome = cmd_apply(
        git_repo,
        "write",
        path="tracked.py",
        content="new\n",
    )
    assert outcome["verdict"] == "pass"
    assert (git_repo / "tracked.py").read_text(encoding="utf-8") == "new\n"
    record = load_record(git_repo)
    assert record is not None
    assert int(record.get("mutationsUsed") or 0) == 1
    assert record.get("consumedAt") is None


def test_surface_window_multi_use(git_repo: Path) -> None:
    _write_prework(git_repo, budget=3)
    for i in range(3):
        outcome = cmd_apply(git_repo, "write", path="tracked.py", content=f"v{i}\n")
        assert outcome["verdict"] == "pass"
    record = load_record(git_repo)
    assert record is not None
    assert int(record.get("mutationsUsed") or 0) == 3
    assert record.get("consumedAt") is not None
    assert validate_fresh_record(record) == "exhausted-prework-surface-window"


def test_shell_tracked_write_denied(git_repo: Path) -> None:
    cause = shell_tracked_mutation_cause("echo x > tracked.py", git_repo)
    assert cause == "shell-tracked-mutation-unsupported"
    payload = {
        "tool_name": "Shell",
        "tool_input": {"command": "echo x > tracked.py"},
        "workspace_roots": [str(git_repo)],
    }
    result = evaluate_pre_tool_use(payload, git_repo)
    assert result.verdict == "fail"
    assert result.cause == "shell-tracked-mutation-unsupported"


def test_shell_read_allowed(git_repo: Path) -> None:
    cause = shell_tracked_mutation_cause("git status --short", git_repo)
    assert cause is None
    payload = {
        "tool_name": "Shell",
        "tool_input": {"command": "git status --short"},
        "workspace_roots": [str(git_repo)],
    }
    result = evaluate_pre_tool_use(payload, git_repo)
    assert result.verdict == "skip"


def test_shell_bypass_python_write_denied(git_repo: Path) -> None:
    cmd = "python3 -c \"open('tracked.py','w').write('x')\""
    cause = shell_tracked_mutation_cause(cmd, git_repo)
    assert cause == "shell-tracked-mutation-unsupported"


def test_wrapper_str_replace(git_repo: Path) -> None:
    _write_prework(git_repo)
    outcome = cmd_apply(
        git_repo,
        "str-replace",
        path="tracked.py",
        old_string="old",
        new_string="new",
    )
    assert outcome["verdict"] == "pass"
    assert (git_repo / "tracked.py").read_text(encoding="utf-8") == "new\n"
