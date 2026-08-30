"""PRD 337 R7 — deliver run-entry orchestrator adopt and branch-type resolution."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from wave_deliver import (  # noqa: E402
    ensure_run_entry_orchestrator,
    resolve_run_entry_target,
    resolve_type,
)


@pytest.fixture(autouse=True)
def shipwright_scripts_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHIPWRIGHT_SCRIPTS", str(SCRIPT_DIR.resolve()))
    monkeypatch.delenv("SW_DELIVER_RUN_ID", raising=False)
    monkeypatch.delenv("SW_RUN_ID", raising=False)
    monkeypatch.setattr("halt_resume.enrich_fail_extra", lambda *_a, **_k: None)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / ".gitignore").write_text(".cursor/\n.sw-worktrees/\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-qm", "init")
    _git(tmp_path, "branch", "-M", "main")
    return tmp_path


def _write_task_list(
    repo: Path,
    *,
    slug: str = "demo-feature",
    extra_frontmatter: str = "",
) -> str:
    docs = repo / "docs" / "prds" / f"337-{slug}"
    docs.mkdir(parents=True, exist_ok=True)
    rel = f"docs/prds/337-{slug}/tasks-337-{slug}.md"
    body = f"""---
type: tasks
id: tasks-337-{slug}
frozen: true
{extra_frontmatter}---

# Tasks

### 1. Demo

- [ ] 1.1 Do work
"""
    (repo / rel).write_text(body, encoding="utf-8")
    _git(repo, "add", rel)
    _git(repo, "commit", "-qm", f"add {rel}")
    return rel


def _capture_fail(capsys: pytest.CaptureFixture[str], fn) -> dict:
    with pytest.raises(SystemExit) as exc:
        fn()
    assert exc.value.code == 20
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload.get("verdict") == "fail"
    return payload


@pytest.mark.parametrize(
    "args,frontmatter,plan_type,expected",
    [
        (["--type", "fix"], {"type": "tasks"}, None, "fix"),
        ([], {"type": "tasks"}, "chore", "chore"),
        ([], {"type": "fix"}, None, "fix"),
        ([], {"type": "prd"}, None, "feat"),
    ],
)
def test_resolve_type_precedence(
    args: list[str],
    frontmatter: dict[str, str],
    plan_type: str | None,
    expected: str,
) -> None:
    assert resolve_type(args, frontmatter, plan_target_type=plan_type) == expected


def test_inferred_branch_type_from_task_list(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    rel = _write_task_list(repo, slug="typed-demo")
    (repo / ".cursor").mkdir(parents=True, exist_ok=True)
    plan = {
        "target": {"type": "fix", "slug": "typed-demo", "branch": "fix/typed-demo"},
        "items": [],
    }
    (repo / ".cursor" / "sw-deliver-plan.json").write_text(
        json.dumps(plan), encoding="utf-8"
    )
    target = resolve_run_entry_target(repo, rel)
    assert target["type"] == "fix"
    assert target["branch"] == "fix/typed-demo"


def test_first_provision_from_bare_main(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    rel = _write_task_list(repo, slug="bare-main-demo")
    _git(repo, "checkout", "-qb", "feat/bare-main-demo")
    _git(repo, "commit", "--allow-empty", "-qm", "feature")
    _git(repo, "checkout", "-q", "main")

    result = ensure_run_entry_orchestrator(repo, rel)
    assert result["autoProvisioned"] is True
    assert result["target"]["branch"] == "feat/bare-main-demo"
    orch = Path(result["orchestratorPath"])
    assert orch.is_dir()
    assert (orch / ".git").exists()


def test_repeated_adoption_idempotent(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    rel = _write_task_list(repo, slug="repeat-demo")
    _git(repo, "checkout", "-qb", "feat/repeat-demo")
    _git(repo, "commit", "--allow-empty", "-qm", "feature")
    _git(repo, "checkout", "-q", "main")
    wt = repo / ".sw-worktrees" / "repeat-demo-orchestrator"
    _git(repo, "worktree", "add", "-q", str(wt), "feat/repeat-demo")

    first = ensure_run_entry_orchestrator(repo, rel)
    second = ensure_run_entry_orchestrator(repo, rel)
    assert first.get("adopted") is True
    assert second.get("adopted") is True
    assert second.get("idempotent") is True
    assert first["orchestratorPath"] == second["orchestratorPath"]


def test_conflicting_worktree_branch_mismatch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _init_repo(tmp_path)
    rel = _write_task_list(repo, slug="branch-conflict")
    _git(repo, "checkout", "-qb", "feat/branch-conflict")
    _git(repo, "commit", "--allow-empty", "-qm", "feature")
    _git(repo, "checkout", "-qb", "feat/wrong-branch")
    _git(repo, "commit", "--allow-empty", "-qm", "wrong")
    _git(repo, "checkout", "-q", "main")
    wt = repo / ".sw-worktrees" / "branch-conflict-orchestrator"
    _git(repo, "worktree", "add", "-q", str(wt), "feat/wrong-branch")

    payload = _capture_fail(
        capsys, lambda: ensure_run_entry_orchestrator(repo, rel)
    )
    assert payload["halt"] == "orchestrator-branch-mismatch"
    assert "feat/branch-conflict" in payload.get("error", "")


def test_conflicting_worktree_dirty(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _init_repo(tmp_path)
    rel = _write_task_list(repo, slug="dirty-orch")
    _git(repo, "checkout", "-qb", "feat/dirty-orch")
    _git(repo, "commit", "--allow-empty", "-qm", "feature")
    _git(repo, "checkout", "-q", "main")
    wt = repo / ".sw-worktrees" / "dirty-orch-orchestrator"
    _git(repo, "worktree", "add", "-q", str(wt), "feat/dirty-orch")
    (wt / "dirty.txt").write_text("x\n", encoding="utf-8")
    _git(repo, "checkout", "-q", "main")

    with patch("halt_resume.enrich_fail_extra"):
        payload = _capture_fail(
            capsys, lambda: ensure_run_entry_orchestrator(repo, rel)
        )
    assert payload["halt"] == "dirty-orchestrator"


def test_orchestrator_path_conflict(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _init_repo(tmp_path)
    rel = _write_task_list(repo, slug="path-conflict")
    _git(repo, "checkout", "-qb", "feat/path-conflict")
    _git(repo, "commit", "--allow-empty", "-qm", "feature")
    _git(repo, "checkout", "-q", "main")
    conflict = repo / ".sw-worktrees" / "path-conflict-orchestrator"
    conflict.mkdir(parents=True)
    (conflict / "not-a-worktree.txt").write_text("blocker\n", encoding="utf-8")

    payload = _capture_fail(
        capsys, lambda: ensure_run_entry_orchestrator(repo, rel)
    )
    assert payload["halt"] == "orchestrator-path-conflict"
