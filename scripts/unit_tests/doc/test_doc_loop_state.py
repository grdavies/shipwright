"""PRD 081 R11 — doc-run resume and idempotency fixtures."""

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
    consume_agent_stage,
    doc_run_directory,
    doc_state_path,
    execute_mechanical_stage,
    handshake_payload,
    load_doc_state,
    provision_doc_run,
    set_pending_checkpoint,
)
from wave_target_lock import acquire_doc_run_lock


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".cursor").mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture(autouse=True)
def anchor_repo(repo: Path):
    with patch("wave_lock._canonical_repo_root_for_locks", return_value=repo):
        yield


def test_fresh_agent_restores_next_action_from_state(repo: Path) -> None:
    provisioned = provision_doc_run(repo, topic="workflow-hardening", tier="Standard")
    assert provisioned["verdict"] == "pass"
    run_id = str(provisioned["runId"])

    state = load_doc_state(repo, run_id)
    assert state["stage"] == "triage"
    assert state["nextAction"] == "triage"

    payload = handshake_payload(
        state=state,
        step={"action": "triage", "stage": "triage", "runId": run_id},
        resumed=False,
    )
    assert payload["action"] == "doc-loop"
    assert payload["awaitAgent"] is True
    assert payload["next"]["stage"] == "triage"


def test_pending_confirm_checkpoint_re_emitted_from_durable_state(repo: Path) -> None:
    provisioned = provision_doc_run(repo, topic="checkpoint-topic", tier="Standard")
    run_id = str(provisioned["runId"])
    state = load_doc_state(repo, run_id)

    consume_agent_stage(repo, state, "triage", outcome={})
    state = load_doc_state(repo, run_id)
    consume_agent_stage(repo, state, "prd", outcome={})
    state = load_doc_state(repo, run_id)
    consume_agent_stage(repo, state, "doc-review", outcome={})
    state = load_doc_state(repo, run_id)
    execute_mechanical_stage(repo, state, "freeze-prd")
    state = load_doc_state(repo, run_id)
    consume_agent_stage(repo, state, "tasks", outcome={})
    state = load_doc_state(repo, run_id)
    execute_mechanical_stage(repo, state, "freeze-tasks")
    state = load_doc_state(repo, run_id)

    set_pending_checkpoint(repo, state)
    state = load_doc_state(repo, run_id)
    assert state["pendingCheckpoint"]["status"] == "pending"

    payload = handshake_payload(
        state=state,
        step={"action": "afterTasks-checkpoint", "stage": "afterTasks-checkpoint", "runId": run_id},
        resumed=True,
    )
    assert payload["awaitHuman"] is True
    assert payload["next"]["checkpoint"]["kind"] == "afterTasks-checkpoint"
    assert payload["next"]["checkpoint"]["status"] == "pending"


def test_idempotent_transition_returns_recorded_outcome_without_side_effect(repo: Path) -> None:
    provisioned = provision_doc_run(repo, topic="idempotent-topic", tier="Standard")
    run_id = str(provisioned["runId"])
    state = load_doc_state(repo, run_id)

    outcome = {"unitIds": {"prd": "prd-081"}, "artifactRevisions": {"prd": {"revision": "1"}}}
    triage_state = dict(state)
    first = consume_agent_stage(repo, triage_state, "triage", outcome=outcome)
    assert first["replayed"] is False

    state_path = doc_state_path(repo, run_id)
    before_mtime = state_path.stat().st_mtime_ns
    snapshot = json.loads(state_path.read_text(encoding="utf-8"))

    second = consume_agent_stage(repo, triage_state, "triage", outcome=outcome)
    assert second["replayed"] is True
    assert second["idempotencyKey"] == first["idempotencyKey"]

    after = json.loads(state_path.read_text(encoding="utf-8"))
    assert after == snapshot
    assert state_path.stat().st_mtime_ns == before_mtime


def test_second_lock_refused_before_run_directory(repo: Path) -> None:
    topic = "exclusive-topic"
    first = acquire_doc_run_lock(repo, topic, "doc-run-a")
    assert first["verdict"] == "pass"

    second = acquire_doc_run_lock(repo, topic, "doc-run-b")
    assert second["verdict"] == "fail"
    assert second["error"] == "doc-run-lock-held"
    assert not doc_run_directory(repo, "doc-run-b").exists()
