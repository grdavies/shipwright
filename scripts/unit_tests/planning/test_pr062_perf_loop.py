"""PRD 062 phase 3 — base-capture, drain, slim manifest, timing (R15 f–g)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

from check_gate_lib import (
    build_gate_payload,
    slim_pr_test_plan_gate,
    validate_pr_test_plan_gate,
)
import resolve_base_branch as rbb
from wave_deliver_loop import (
    DRAIN_STEP_BUDGET_HALT,
    drain_mechanical_enabled,
    execute_mechanical,
)


def test_capture_trunk_from_feat_branch_without_checkout(tmp_git_repo: Path) -> None:
    """R15(f)/R6 — orchestrator-style feat/* HEAD captures trunk SHA, not branch tip."""
    subprocess.run(["git", "branch", "feat/demo"], cwd=tmp_git_repo, check=True, capture_output=True)
    subprocess.run(["git", "checkout", "feat/demo"], cwd=tmp_git_repo, check=True, capture_output=True)
    (tmp_git_repo / "feature.txt").write_text("work\n", encoding="utf-8")
    subprocess.run(["git", "add", "feature.txt"], cwd=tmp_git_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "feat work"],
        cwd=tmp_git_repo,
        check=True,
        capture_output=True,
    )
    result = rbb.capture(tmp_git_repo)
    trunk = result["trunkBase"]
    assert trunk["name"] == "main"
    assert trunk["source"] == "trunk-ref-from-work-branch"
    main_sha = subprocess.run(
        ["git", "rev-parse", "main"],
        cwd=tmp_git_repo,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    feat_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_git_repo,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    assert trunk["sha"] == main_sha
    assert trunk["sha"] != feat_sha


def test_drain_mechanical_defaults_true(repo_root: Path) -> None:
    """R15(f)/R7 — drainMechanical defaults to true when unset."""
    assert drain_mechanical_enabled(repo_root) is True


def test_drain_mechanical_false_from_config(tmp_path: Path) -> None:
    """R15(f)/R7 — drainMechanical false is honored from workflow config."""
    cfg = tmp_path / ".cursor"
    cfg.mkdir(parents=True)
    (cfg / "workflow.config.json").write_text(
        json.dumps({"deliver": {"loop": {"drainMechanical": False}}}),
        encoding="utf-8",
    )
    assert drain_mechanical_enabled(tmp_path) is False


def test_drain_step_budget_halt_constant() -> None:
    """R15(f) — max-steps while still mechanical maps to blocked halt cause."""
    assert DRAIN_STEP_BUDGET_HALT == "conductor:drain-step-budget-exceeded"


def test_slim_pr_test_plan_omits_embedded_manifest(tmp_git_repo: Path) -> None:
    """R15(g)/R8 — gate payload carries path+hash, not full manifest body."""
    manifest = {"fixtures": [{"ciJobName": "unit", "classification": "required"}]}
    slim = slim_pr_test_plan_gate(tmp_git_repo, manifest, ["unit"], [])
    assert slim is not None
    assert "manifest" not in slim
    assert slim["manifestPath"].endswith("pr-test-plan.manifest.json")
    assert slim["manifestSha256"]
    payload = build_gate_payload(
        tmp_git_repo,
        verdict="green",
        reason="ok",
        head_sha="a" * 40,
        review_provider="none",
        cr_reviewed_head="",
        cr_status="off",
        cr_state="off",
        cr_landed=True,
        cr_marker=False,
        cr_skipped=False,
        mins_since=0,
        unresolved=0,
        actionable=0,
        failing=[],
        required_failing=[],
        advisory_failing=[],
        pr_test_plan=manifest,
        required_jobs=["unit"],
        advisory_jobs=[],
        pending=[],
        blocking=[],
        check_count=1,
        deprecations=[],
    )
    gate_plan = payload["prTestPlan"]
    assert gate_plan is not None
    assert "manifest" not in gate_plan
    assert gate_plan["manifestPath"]


def test_validate_pr_test_plan_gate_missing_manifest(tmp_git_repo: Path) -> None:
    """R15(g)/R8 — missing slim manifest file fails closed."""
    manifest = {"fixtures": []}
    slim = slim_pr_test_plan_gate(tmp_git_repo, manifest, [], [])
    assert validate_pr_test_plan_gate(tmp_git_repo, slim) is None
    (tmp_git_repo / slim["manifestPath"]).unlink()
    assert validate_pr_test_plan_gate(tmp_git_repo, slim) == "manifest-missing"


def test_validate_pr_test_plan_gate_hash_mismatch(tmp_git_repo: Path) -> None:
    """R15(g)/R8 — tampered slim manifest hash fails closed."""
    manifest = {"fixtures": []}
    slim = slim_pr_test_plan_gate(tmp_git_repo, manifest, [], [])
    (tmp_git_repo / slim["manifestPath"]).write_text('{"tampered":true}\n', encoding="utf-8")
    assert validate_pr_test_plan_gate(tmp_git_repo, slim) == "manifest-hash-mismatch"


def test_execute_mechanical_includes_elapsed_ms(repo_root: Path) -> None:
    """R15(g)/R9 — mechanical step results include elapsedMs timing."""
    state = {"verdict": "running", "phases": {}}
    plan = {"target": {"branch": "feat/x"}}
    step = {"action": "merge-enqueue", "phaseSlug": "alpha"}
    with patch(
        "wave_deliver_loop._execute_mechanical_inner",
        return_value={"executed": "merge-enqueue"},
    ):
        result = execute_mechanical(repo_root, state, plan, step)
    assert isinstance(result.get("elapsedMs"), int)
    assert result["elapsedMs"] >= 0
