"""PRD 081 R25 — transition and mutation receipt discipline."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

from wave_transition_receipt import (
    ExternalMutationIncompleteError,
    IncompleteReceiptError,
    begin_transition,
    build_input_revisions,
    build_output_revision,
    complete_transition,
    find_incomplete_receipt,
    persist_external_mutation_receipt,
    read_receipt,
    receipt_path,
)


@pytest.fixture
def run_id() -> str:
    return "deliver-receipt-test"


def test_transition_persists_complete_receipt(repo_root: Path, run_id: str) -> None:
    state = {"runId": run_id, "verdict": "running", "nextAction": "state-init"}
    plan = {"mode": "phase", "target": {"branch": "feat/demo"}}
    input_revisions = build_input_revisions(repo_root, state, plan)
    pending = begin_transition(
        repo_root,
        run_id,
        "state-init",
        input_revisions=input_revisions,
        actor="tester",
    )
    key = str(pending["idempotencyKey"])
    completed = complete_transition(
        repo_root,
        run_id,
        key,
        output_revision=build_output_revision({**state, "specSeed": {"at": "now"}}),
        actor="tester",
    )
    stored = read_receipt(repo_root, run_id, key)
    assert stored is not None
    assert stored["status"] == "complete"
    assert stored["transitionName"] == "state-init"
    assert stored["idempotencyKey"] == key
    assert stored["inputRevisions"] == input_revisions
    assert stored["outputRevision"] is not None
    assert stored["actor"] == "tester"
    assert stored["timestamp"]
    assert completed["completedAt"]


def test_incomplete_receipt_detected_on_resume(repo_root: Path, run_id: str) -> None:
    state = {"runId": run_id, "verdict": "running"}
    input_revisions = build_input_revisions(repo_root, state, None)
    pending = begin_transition(
        repo_root,
        run_id,
        "base-capture",
        input_revisions=input_revisions,
    )
    key = str(pending["idempotencyKey"])
    assert receipt_path(repo_root, run_id, key).with_name(
        receipt_path(repo_root, run_id, key).name + ".pending"
    ).is_file()

    incomplete = find_incomplete_receipt(repo_root, run_id)
    assert incomplete is not None
    assert incomplete["transitionName"] == "base-capture"
    assert incomplete["status"] == "pending"

    with pytest.raises(IncompleteReceiptError):
        begin_transition(
            repo_root,
            run_id,
            "base-capture",
            input_revisions=input_revisions,
            idempotency_key=key,
        )


def test_external_mutation_receipt_requires_exit_and_remote_state(
    repo_root: Path, run_id: str
) -> None:
    input_revisions = {"push": {"label": "push", "hash": "abc"}}
    with pytest.raises(ExternalMutationIncompleteError):
        persist_external_mutation_receipt(
            repo_root,
            run_id,
            "git-push",
            idempotency_key="push-1",
            input_revisions=input_revisions,
            output_revision={"remote": {"label": "remote", "hash": "def"}},
            exit_status=None,
            remote_state={"ref": "feat/demo"},
        )
    with pytest.raises(ExternalMutationIncompleteError):
        persist_external_mutation_receipt(
            repo_root,
            run_id,
            "git-push",
            idempotency_key="push-1",
            input_revisions=input_revisions,
            output_revision={"remote": {"label": "remote", "hash": "def"}},
            exit_status=1,
            remote_state=None,
        )


def test_failed_push_surfaces_with_persisted_receipt(repo_root: Path, run_id: str) -> None:
    input_revisions = {"branch": {"label": "branch", "hash": "deadbeef"}}
    output_revision = {"remote": {"label": "remote", "hash": "cafebabe"}}
    receipt = persist_external_mutation_receipt(
        repo_root,
        run_id,
        "git-push",
        idempotency_key="push-failed",
        input_revisions=input_revisions,
        output_revision=output_revision,
        exit_status=128,
        remote_state={"ref": "feat/demo", "remoteHead": None},
        actor="tester",
    )
    stored = read_receipt(repo_root, run_id, "push-failed")
    assert stored is not None
    assert stored["status"] == "failed"
    assert stored["externalMutation"]["exitStatus"] == 128
    assert stored["externalMutation"]["remoteState"]["remoteHead"] is None
    assert receipt["cause"] == "external-mutation-exit-128"
