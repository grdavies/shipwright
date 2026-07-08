"""Pytest port of run_planning_scheduler_fixtures.py (PRD 054 W2 behavioral)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_PKG = "scripts/unit_tests/git"
_HARNESS = "harness_planning_scheduler.py"


def _load_harness(repo_root: Path):
    path = repo_root / _PKG / _HARNESS
    for entry in (str(repo_root / "scripts" / "test"), str(repo_root / "scripts")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    spec = importlib.util.spec_from_file_location("harness_planning_scheduler", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load harness {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.git
def test_planning_scheduler_tmp_git_repo_ready(tmp_git_repo: Path) -> None:
    """R15 — shared tmp_git_repo fixture is usable for W2 git scenarios."""
    assert (tmp_git_repo / ".git").is_dir()


@pytest.mark.git
def test_planning_scheduler_behavior(repo_root: Path, sw_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in sw_env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.chdir(repo_root)
    mod = _load_harness(repo_root)
    assert int(mod.main()) == 0


def test_planning_scheduler_harness_present(repo_root: Path) -> None:
    """R16 — harness module must exist (fail-closed if port regresses)."""
    assert (repo_root / _PKG / _HARNESS).is_file()

_Gap051_TASK_REL = "docs/prds/058-dispatch-loop-hardening/tasks-058-dispatch-loop-hardening.md"
_Gap051_TASK_PATH = Path(_Gap051_TASK_REL)


def _import_planning_deliver_gate():
    import sys

    scripts = Path(__file__).resolve().parents[2]
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import planning_deliver_gate as gate

    return gate


def test_unit_id_from_task_list_parent_directory_derivation() -> None:
    """R1 — docs/prds/<n>-<slug>/ derives <n>-prd-<slug>, not prd-<n>-<slug>."""
    gate = _import_planning_deliver_gate()
    unit_id = gate.unit_id_from_task_list(_Gap051_TASK_PATH)
    assert unit_id == "058-prd-dispatch-loop-hardening"
    assert unit_id != "prd-058-dispatch-loop-hardening"


def test_unit_id_derivation_joint_fixture_distinct_ids() -> None:
    """R4 — parent-directory PRD graph id and filename-stem store id stay distinct."""
    gate = _import_planning_deliver_gate()
    import planning_materialize as pm

    parent_id = gate.unit_id_from_task_list(_Gap051_TASK_PATH)
    rel_id = pm.unit_id_from_task_list_rel(_Gap051_TASK_REL)
    assert parent_id == "058-prd-dispatch-loop-hardening"
    assert rel_id == "tasks-058-dispatch-loop-hardening"
    assert parent_id != rel_id


def _seed_gap051_e2e_repo(repo: Path) -> None:
    prd_dir = repo / "docs/planning/prd/058-prd-gap051-e2e"
    prd_dir.mkdir(parents=True)
    (prd_dir / "058-prd-gap051-e2e.md").write_text(
        """---
id: 058-prd-gap051-e2e
type: prd
status: planned
title: gap051 e2e
visibility: public
priority: 5
depends: [058-prd-gap051-missing]
---
# gap051 e2e
""",
        encoding="utf-8",
    )
    task_dir = repo / "docs/prds/058-gap051-e2e"
    task_dir.mkdir(parents=True)
    (task_dir / "tasks-058-gap051-e2e.md").write_text(
        """---
frozen: true
prd: docs/prds/058-gap051-e2e/058-prd-gap051-e2e.md
---
### 1. Phase
- [ ] 1.1 Task
""",
        encoding="utf-8",
    )


@pytest.mark.git
def test_dependency_gate_hard_fails_on_unmet_depends(tmp_git_repo: Path) -> None:
    """R3 — explicit depends edge hard-fails; never unit-not-in-graph pass."""
    gate = _import_planning_deliver_gate()
    _seed_gap051_e2e_repo(tmp_git_repo)
    task_path = tmp_git_repo / "docs/prds/058-gap051-e2e/tasks-058-gap051-e2e.md"
    with pytest.raises(SystemExit) as exc:
        gate.dependency_gate(tmp_git_repo, task_path)
    assert exc.value.code == gate.GATE_FAIL_EXIT


@pytest.mark.git
def test_unknown_layout_task_list_fails_closed(tmp_git_repo: Path) -> None:
    """R5/R6 — non-canonical task-list layout fails closed."""
    gate = _import_planning_deliver_gate()
    misseed = tmp_git_repo / ".cursor/planning-materialized/docs/prds/058-gap051-e2e/tasks-058-gap051-e2e.md"
    misseed.parent.mkdir(parents=True)
    misseed.write_text("---\nfrozen: true\n---\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        gate.dependency_gate(tmp_git_repo, misseed)
    assert exc.value.code == gate.GATE_FAIL_EXIT


@pytest.mark.git
def test_allowlisted_new_unit_not_in_graph_passes(tmp_git_repo: Path) -> None:
    """R5 — canonical, not-yet-frozen task list may pass when absent from graph."""
    gate = _import_planning_deliver_gate()
    task_dir = tmp_git_repo / "docs/prds/099-new-unit"
    task_dir.mkdir(parents=True)
    task_path = task_dir / "tasks-099-new-unit.md"
    task_path.write_text("---\nstatus: draft\n---\n", encoding="utf-8")
    out = gate.dependency_gate(tmp_git_repo, task_path)
    assert out["verdict"] == "pass"
    assert out.get("note") == "unit-not-in-graph-allowlisted"

def test_resolve_gap_051_for_prd_058_flips_legacy_row(tmp_path: Path) -> None:
    """R6 — gap_backlog closes GAP-051 for PRD 058 phase delivery."""
    import sys

    scripts = Path(__file__).resolve().parents[2]
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import gap_backlog as gb

    gap_path = tmp_path / "docs/prds/GAP-BACKLOG.md"
    gap_path.parent.mkdir(parents=True)
    gap_path.write_text(
        """# Gap backlog

| resolved | 0 |
| scheduled | 0 |
| open | 1 |

| ID | Status | Schedule | Title |
|----|--------|----------|-------|
| GAP-051 | open | — | Dependency gate unit-id derivation |
""",
        encoding="utf-8",
    )
    result = gb.resolve_gap_051_for_prd_058(tmp_path, scope_note="PRD 058 phase 1")
    assert result["verdict"] == "pass"
    assert "GAP-051" in result["flipped"]
    backlog = gb.parse_gap_backlog(gap_path.read_text(encoding="utf-8"))
    row = next(r for r in backlog.rows if r.gap_id == "GAP-051")
    assert row.status.lower() == "resolved"
