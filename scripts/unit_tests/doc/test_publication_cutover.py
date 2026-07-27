"""PRD 081 R15/R25 — publication cutover and receipt fixtures."""

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
    UNREACHABLE_PUBLICATION_STAGES,
    acknowledge_checkpoint,
    assert_publication_stage_reachable,
    deliver_handoff_reachable,
    execute_mechanical_stage,
    load_doc_state,
    provision_doc_run,
    publication_mode,
    run_feature_seed,
    save_doc_state,
)
from wave_transition_receipt import persist_external_mutation_receipt


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".cursor").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "brainstorms").mkdir(parents=True)
    (root / "docs" / "prds" / "081-demo").mkdir(parents=True)
    return root


@pytest.fixture(autouse=True)
def anchor_repo(repo: Path):
    with patch("wave_lock._canonical_repo_root_for_locks", return_value=repo):
        yield


def _verified_receipt(artifact: str) -> dict:
    return {
        "verdict": "pass",
        "artifact": artifact,
        "owner": "doc-loop:test",
        "lifecycleState": "frozen",
        "durabilityState": "verified",
        "revision": "abc123",
    }


def _state_with_artifacts(repo: Path, run_id: str) -> dict:
    bs = repo / "docs/brainstorms/demo-brainstorm.md"
    bs.write_text("---\ntype: brainstorm\n---\n# BS\n", encoding="utf-8")
    prd = repo / "docs/prds/081-demo/prd.md"
    prd.write_text(
        "---\ntype: prd\nfrozen: true\nbrainstorm: docs/brainstorms/demo-brainstorm.md\n---\n# PRD\n",
        encoding="utf-8",
    )
    tasks = repo / "docs/prds/081-demo/tasks-081-demo.md"
    tasks.write_text("---\ntype: tasks\nfrozen: true\n---\n# Tasks\n", encoding="utf-8")
    state = load_doc_state(repo, run_id)
    state["unitIds"] = {"prd": "081-prd-demo", "tasks": "tasks-081-demo"}
    state["artifactPaths"] = {
        "prd": "docs/prds/081-demo/prd.md",
        "tasks": "docs/prds/081-demo/tasks-081-demo.md",
    }
    state["artifactRevisions"] = {
        "prd": _verified_receipt("docs/prds/081-demo/prd.md"),
        "tasks": _verified_receipt("docs/prds/081-demo/tasks-081-demo.md"),
    }
    state["pendingRelatedWork"] = {"status": "acknowledged"}
    save_doc_state(repo, state)
    return state


def test_docs_pr_unreachable_from_driver() -> None:
    for stage in UNREACHABLE_PUBLICATION_STAGES:
        with pytest.raises(SystemExit):
            assert_publication_stage_reachable(stage)


def test_file_store_feature_seed_without_docs_pr(repo: Path) -> None:
    with patch(
        "planning_artifact_handle.issue_store_separate_project_effective",
        return_value=False,
    ), patch(
        "doc_loop.run_feature_seed",
        return_value={
            "verdict": "pass",
            "action": "feature-seed",
            "receipt": {"status": "complete", "publicationMode": "file-store-feature-seed"},
        },
    ):
        provisioned = provision_doc_run(repo, topic="pub-cutover", tier="Full")
        run_id = str(provisioned["runId"])
        state = _state_with_artifacts(repo, run_id)
        state["stage"] = "feature-seed"
        save_doc_state(repo, state)
        result = execute_mechanical_stage(repo, state, "feature-seed")
    assert result.get("halted") is not True
    state = load_doc_state(repo, run_id)
    assert state.get("featureSeedReceipt") is not None
    assert state["stage"] == "complete"


def test_separate_project_skips_local_publication(repo: Path) -> None:
    provisioned = provision_doc_run(repo, topic="store-only", tier="Full")
    run_id = str(provisioned["runId"])
    state = _state_with_artifacts(repo, run_id)
    with patch("planning_artifact_handle.issue_store_separate_project_effective", return_value=True):
        assert publication_mode(repo) == "separate-project-store-only"
        outcome = run_feature_seed(repo, state)
    assert outcome["skipped"] is True
    assert outcome["reason"] == "separate-project-store-only"


def test_feature_seed_receipt_persists_exit_and_remote_state(repo: Path) -> None:
    run_id = "doc-loop-receipt-test"
    input_revisions = {"seed": {"label": "seed", "hash": "abc"}}
    output_revision = {"remote": {"label": "remote", "hash": "def"}}
    receipt = persist_external_mutation_receipt(
        repo,
        run_id,
        "feature-seed",
        idempotency_key="feature-seed-1",
        input_revisions=input_revisions,
        output_revision=output_revision,
        exit_status=0,
        remote_state={"branch": "feat/demo", "commit": "deadbeef"},
        actor="doc-loop:test",
    )
    assert receipt["status"] == "complete"
    assert receipt["externalMutation"]["exitStatus"] == 0
    assert receipt["externalMutation"]["remoteState"]["commit"] == "deadbeef"


def test_deliver_handoff_requires_feature_seed_receipt(repo: Path) -> None:
    provisioned = provision_doc_run(repo, topic="handoff-gate", tier="Standard")
    run_id = str(provisioned["runId"])
    state = _state_with_artifacts(repo, run_id)
    state["stage"] = "afterTasks-checkpoint"
    save_doc_state(repo, state)
    assert deliver_handoff_reachable(state) is False

    state["featureSeedReceipt"] = {"status": "complete"}
    state["stage"] = "complete"
    save_doc_state(repo, state)
    assert deliver_handoff_reachable(load_doc_state(repo, run_id)) is True
