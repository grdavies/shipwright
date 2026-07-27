"""PRD 081 R12/R13 — durability failure and related-work gating fixtures."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

from doc_loop import (
    acknowledge_related_work,
    deliver_handoff_reachable,
    execute_mechanical_stage,
    load_doc_state,
    provision_doc_run,
    save_doc_state,
    set_pending_checkpoint,
)
from planning_related import Proposal, scan_related


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".cursor").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "prds" / "081-prd-demo").mkdir(parents=True)
    prd = root / "docs/prds/081-prd-demo/prd.md"
    prd.write_text("---\ntype: prd\nid: 081-prd-demo\n---\n# Demo\n", encoding="utf-8")
    import subprocess

    subprocess.run(["git", "init"], cwd=root, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=root, capture_output=True, check=True)
    return root


@pytest.fixture(autouse=True)
def anchor_repo(repo: Path):
    with patch("wave_lock._canonical_repo_root_for_locks", return_value=repo):
        yield


def _state_with_artifacts(repo: Path, run_id: str) -> dict:
    state = load_doc_state(repo, run_id)
    state["unitIds"] = {"prd": "081-prd-demo", "tasks": "tasks-081-demo"}
    state["artifactPaths"] = {
        "prd": "docs/prds/081-prd-demo/prd.md",
        "tasks": "docs/prds/081-prd-demo/tasks-081-demo.md",
    }
    save_doc_state(repo, state)
    return state


def test_commit_failure_halts_driver(repo: Path) -> None:
    provisioned = provision_doc_run(repo, topic="durability-halt", tier="Standard")
    run_id = str(provisioned["runId"])
    state = _state_with_artifacts(repo, run_id)

    with patch(
        "doc_loop.freeze_stage_artifact",
        return_value={
            "verdict": "fail",
            "error": "durability-not-verified",
            "halt": "doc-loop:freeze-durability",
            "receipt": {"durabilityState": "failed"},
        },
    ):
        result = execute_mechanical_stage(repo, state, "freeze-prd")

    assert result.get("halted") is True
    state = load_doc_state(repo, run_id)
    assert state["verdict"] == "halted"
    assert deliver_handoff_reachable(state) is False


def test_freeze_record_readback_failure_halts_driver(repo: Path) -> None:
    provisioned = provision_doc_run(repo, topic="readback-halt", tier="Standard")
    run_id = str(provisioned["runId"])
    state = _state_with_artifacts(repo, run_id)

    with patch(
        "doc_loop.freeze_stage_artifact",
        return_value={
            "verdict": "fail",
            "error": "freeze-record-readback-failed",
            "halt": "doc-loop:freeze-durability",
            "receipt": {"durabilityState": "failed", "freezeRecordDigest": None},
        },
    ):
        result = execute_mechanical_stage(repo, state, "freeze-tasks")

    assert result.get("halted") is True
    assert deliver_handoff_reachable(load_doc_state(repo, run_id)) is False


def test_driver_scan_has_no_nested_confirm_prompt(repo: Path) -> None:
    from planning_related import source_from_path

    source = source_from_path(repo, "docs/prds/081-prd-demo/prd.md")
    with patch("planning_related.pg.discover_units", return_value=[]):
        result = scan_related(repo, source, mode="tasks-rescan", driver_invoked=True)
    assert result["driverInvoked"] is True
    assert result.get("humanGated") is False
    assert "confirmList" not in result
    assert "serializedForParent" in result


def test_related_work_stage_gates_progression(repo: Path) -> None:
    provisioned = provision_doc_run(repo, topic="related-gate", tier="Standard")
    run_id = str(provisioned["runId"])
    state = _state_with_artifacts(repo, run_id)
    scan = {
        "verdict": "ok",
        "proposals": [{"id": "gap-001", "score": 0.9, "route": "absorb"}],
        "serializedForParent": [{"id": "gap-001"}],
    }
    with patch("doc_loop.run_related_work_scan", return_value=scan):
        execute_mechanical_stage(repo, state, "related-work")

    state = load_doc_state(repo, run_id)
    assert state["stage"] == "related-work-checkpoint"
    assert state["pendingRelatedWork"]["status"] == "pending"
    assert deliver_handoff_reachable(state) is False

    acknowledge_related_work(repo, state)
    state = load_doc_state(repo, run_id)
    assert state["pendingRelatedWork"]["status"] == "acknowledged"
    assert state["stage"] == "freeze-prd"


def test_checkpoint_blocked_without_durable_artifacts(repo: Path) -> None:
    provisioned = provision_doc_run(repo, topic="checkpoint-gate", tier="Standard")
    run_id = str(provisioned["runId"])
    state = load_doc_state(repo, run_id)
    state["artifactRevisions"] = {
        "prd": {"durabilityState": "verified"},
        "tasks": {"durabilityState": "pending"},
    }
    with pytest.raises(SystemExit) as exc:
        set_pending_checkpoint(repo, state)
    assert exc.value.code == 20
