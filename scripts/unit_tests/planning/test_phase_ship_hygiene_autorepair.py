"""PRD 278 phase-ship hygiene safe auto-repair regressions (R1–R2, D2, D4)."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import phase_ship_hygiene as psh


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_gap_gate(repo_root: Path):
    path = repo_root / "scripts" / "gap-check-gate.py"
    spec = importlib.util.spec_from_file_location("gap_check_gate", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(repo_root / "scripts"))
    spec.loader.exec_module(mod)
    return mod


def test_forged_gap_check_pass_refused(tmp_git_repo: Path, repo_root: Path) -> None:
    """R2/D4 — binding pass without evaluationProvenance is forged."""
    phase_slug = "hygiene-forged"
    head = subprocess.run(
        ["git", "-C", str(tmp_git_repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    status_dir = tmp_git_repo / ".cursor" / "sw-deliver-runs" / phase_slug
    status_dir.mkdir(parents=True)
    (status_dir / "gap-check.status.json").write_text(
        json.dumps({"verdict": "pass", "binding": True, "head": head, "updatedAt": _utc_now()}),
        encoding="utf-8",
    )
    assert psh.is_forged_gap_check_status(json.loads((status_dir / "gap-check.status.json").read_text()))
    gap_gate = _load_gap_gate(repo_root)
    ok, cause = gap_gate.deliver_gap_check_ok(tmp_git_repo, phase_slug, require_status=True)
    assert not ok
    assert cause == "gap-check-forged-pass"


def test_gap_check_missing_auto_repair_from_ship_steps(tmp_git_repo: Path, repo_root: Path) -> None:
    """R1(a) — missing gap-check status repairs after ship-steps prove evaluation."""
    phase_slug = "hygiene-gap-repair"
    head = subprocess.run(
        ["git", "-C", str(tmp_git_repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    run_dir = tmp_git_repo / ".cursor" / "sw-deliver-runs" / phase_slug
    run_dir.mkdir(parents=True)
    (run_dir / "ship-steps.json").write_text(
        json.dumps(
            {
                "chain": ["sw-tmp-init", "sw-execute", "gap-check", "sw-commit"],
                "lastCompletedStep": "gap-check",
                "updatedAt": _utc_now(),
            }
        ),
        encoding="utf-8",
    )
    repair = psh.try_auto_repair_gap_check_missing(tmp_git_repo, phase_slug)
    assert repair.get("verdict") == "pass", repair
    gap_gate = _load_gap_gate(repo_root)
    ok, cause = gap_gate.deliver_gap_check_ok(tmp_git_repo, phase_slug, require_status=True)
    assert ok, cause
    doc = json.loads((run_dir / "gap-check.status.json").read_text(encoding="utf-8"))
    assert doc.get("evaluationProvenance", {}).get("evaluationHead") == head


def test_gap_check_missing_without_evaluation_stays_blocked(tmp_git_repo: Path) -> None:
    """R1 — no evaluation evidence → typed cause + resumeCommand, no forged pass."""
    phase_slug = "hygiene-gap-blocked"
    repair = psh.try_auto_repair_gap_check_missing(tmp_git_repo, phase_slug)
    assert repair.get("verdict") == "fail"
    assert repair.get("cause") == "gap-check-missing"
    assert repair.get("resumeCommand", "").startswith("/sw-ship --phase-mode")


def test_pr_test_plan_manifest_auto_repair(tmp_git_repo: Path, repo_root: Path) -> None:
    """R1(c) — orchestrator gate-cache manifest mirrored from core manifest."""
    orch = tmp_git_repo / "orch"
    orch.mkdir()
    subprocess.run(["git", "init"], cwd=orch, check=True, capture_output=True)
    state = {
        "target": {"branch": "feat/demo"},
        "source_task_list": "docs/prds/278-deliver-ship-closeout-hardening/tasks-278-deliver-ship-closeout-hardening.md",
        "orchestratorWorktree": {"path": str(orch)},
    }
    repair = psh.try_auto_repair_pr_test_plan_manifest(tmp_git_repo, state)
    assert repair.get("verdict") == "pass", repair
    cache = orch / ".cursor" / "sw-gate-cache" / "pr-test-plan.manifest.json"
    assert cache.is_file()


def test_tasks_currency_auto_repair_refuses_invented_ledger(tmp_git_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R2 — auto-repair does not invent ledger completion for unchecked work."""
    state = {
        "source_task_list": "docs/prds/demo/tasks-demo.md",
        "target": {"branch": "feat/demo"},
    }
    plan = {"source_task_list": state["source_task_list"]}

    def _always_diverge(*_args, **_kwargs):
        return False, "tasks-currency-divergence"

    def _resync_fail(*_args, **_kwargs):
        return {"verdict": "fail", "divergences": ["3.1"], "action": "materialize-resync"}

    monkeypatch.setattr("wave_deliver_loop.tasks_currency_ok", _always_diverge)
    monkeypatch.setattr("wave_deliver.phase_entry_currency_check", lambda *a, **k: _resync_fail())

    repair = psh.try_auto_repair_tasks_currency_divergence(tmp_git_repo, state, plan)
    assert repair.get("verdict") == "fail"
    assert repair.get("cause") == "tasks-currency-divergence"
    assert repair.get("resumeCommand")
