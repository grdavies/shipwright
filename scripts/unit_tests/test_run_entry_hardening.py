"""PRD 065 phase 7 — run-entry hardening and PRD-064 depends-on edge (R11–R13, R18)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, _ROOT / rel)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


wave_deliver = _load("wave_deliver_run_entry", "wave_deliver.py")
wave_lifecycle = _load("wave_lifecycle_run_entry", "wave_lifecycle.py")
planning_deliver_gate = _load("planning_deliver_gate_run_entry", "planning_deliver_gate.py")


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=tmp_path, check=True)
    scripts = tmp_path / "scripts"
    if not scripts.exists():
        scripts.symlink_to(_ROOT, target_is_directory=True)
    return tmp_path


@pytest.mark.parametrize(
    "args,frontmatter,plan_type,expected",
    [
        (["--type", "fix"], {"type": "tasks"}, None, "fix"),
        ([], {"type": "tasks"}, "chore", "chore"),
        ([], {"type": "tasks"}, None, "feat"),
        ([], {"type": "prd"}, None, "feat"),
        ([], {"type": "brainstorm"}, "docs", "docs"),
    ],
)
def test_resolve_type_precedence(
    args: list[str],
    frontmatter: dict[str, str],
    plan_type: str | None,
    expected: str,
) -> None:
    assert wave_deliver.resolve_type(args, frontmatter, plan_target_type=plan_type) == expected


def test_orchestrator_provision_adopt_clean(git_repo: Path) -> None:
    subprocess.run(["git", "checkout", "-qb", "feat/demo"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "--allow-empty", "-qm", "demo"], cwd=git_repo, check=True)
    subprocess.run(["git", "checkout", "-q", "main"], cwd=git_repo, check=True)
    subprocess.run(
        [
            "git",
            "worktree",
            "add",
            "-q",
            str(git_repo / ".sw-worktrees/demo-orchestrator"),
            "feat/demo",
        ],
        cwd=git_repo,
        check=True,
    )
    subprocess.run(["git", "checkout", "-q", "main"], cwd=git_repo, check=True)

    with pytest.raises(SystemExit) as exc:
        wave_lifecycle.cmd_orchestrator_provision(git_repo, ["--target", "feat/demo"])
    assert exc.value.code == 0


def test_orchestrator_provision_fail_dirty(git_repo: Path) -> None:
    subprocess.run(["git", "checkout", "-qb", "feat/demo"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "--allow-empty", "-qm", "demo"], cwd=git_repo, check=True)
    subprocess.run(["git", "checkout", "-q", "main"], cwd=git_repo, check=True)
    wt = git_repo / ".sw-worktrees/demo-orchestrator"
    subprocess.run(
        ["git", "worktree", "add", "-q", str(wt), "feat/demo"],
        cwd=git_repo,
        check=True,
    )
    (wt / "dirty.txt").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "checkout", "-q", "main"], cwd=git_repo, check=True)

    with pytest.raises(SystemExit) as exc:
        wave_lifecycle.cmd_orchestrator_provision(git_repo, ["--target", "feat/demo"])
    assert exc.value.code == 20


def test_assert_entry_auto_provisions_from_bare_main(git_repo: Path) -> None:
    subprocess.run(["git", "checkout", "-qb", "feat/demo"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "--allow-empty", "-qm", "demo"], cwd=git_repo, check=True)
    subprocess.run(["git", "checkout", "-q", "main"], cwd=git_repo, check=True)
    (git_repo / ".cursor").mkdir(parents=True, exist_ok=True)
    plan = {
        "mode": "phase",
        "target": {"type": "feat", "slug": "demo", "branch": "feat/demo"},
        "items": [{"id": "1", "slug": "alpha", "title": "A", "branch": "feat/demo-phase-alpha"}],
    }
    (git_repo / ".cursor/sw-deliver-plan.json").write_text(json.dumps(plan), encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        wave_lifecycle.cmd_assert_entry(git_repo, ["--plan", ".cursor/sw-deliver-plan.json"])
    assert exc.value.code == 0
    assert (git_repo / ".sw-worktrees/demo-orchestrator").is_dir()


def test_prd_064_hard_depends_blocks_when_incomplete(git_repo: Path) -> None:
    by_id = {
        planning_deliver_gate.PRD_064_UNIT_ID: planning_deliver_gate.pg.GraphUnit(
            id=planning_deliver_gate.PRD_064_UNIT_ID,
            unit_type="prd",
            status="draft",
            priority=0,
        )
    }
    blocking = planning_deliver_gate.unmet_hard_prerequisites(
        git_repo,
        "065-prd-turn-independent-ship-loop-and-gate-evidence",
        by_id,
    )
    assert blocking == [planning_deliver_gate.PRD_064_UNIT_ID]
