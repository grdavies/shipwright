"""PRD 081 R11 — doc-run resume and idempotency fixtures."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

from doc_loop import (
    cmd_doc_loop,
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


def test_consume_advances_exactly_one_agent_stage(
    repo: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    provisioned = provision_doc_run(repo, topic="one-shot-consume", tier="Full")
    run_id = str(provisioned["runId"])
    outcome = {
        "verdict": "pass",
        "tier": "Full",
        "source": "test",
    }

    with pytest.raises(SystemExit) as exc_info:
        cmd_doc_loop(
            repo,
            [
                "--run-id",
                run_id,
                "--consume",
                "--outcome",
                json.dumps(outcome),
            ],
        )

    assert exc_info.value.code in (None, 0)
    payload = json.loads(capsys.readouterr().out)
    assert [step["executed"] for step in payload["stepsTaken"]] == ["triage"]
    assert payload["awaitAgent"] is True
    assert payload["next"]["stage"] == "brainstorm"

    state = load_doc_state(repo, run_id)
    assert state["stage"] == "brainstorm"
    assert state["verdict"] == "running"
    assert len(list((doc_run_directory(repo, run_id) / "receipts").glob("*.json"))) == 1


def _verified_freeze(stage: str) -> dict:
    key = "prd" if stage == "freeze-prd" else "tasks"
    return {
        "verdict": "pass",
        "artifactKey": key,
        "receipt": {
            "owner": "doc-loop:test",
            "durabilityState": "verified",
            "lifecycleState": "frozen",
            "revision": "rev",
        },
    }


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
    with patch("doc_loop.run_related_work_scan", return_value={"verdict": "ok", "proposals": []}):
        execute_mechanical_stage(repo, state, "related-work")
    state = load_doc_state(repo, run_id)
    with patch("doc_loop.freeze_stage_artifact", side_effect=lambda _r, _s, stage: _verified_freeze(stage)):
        execute_mechanical_stage(repo, state, "freeze-prd")
    state = load_doc_state(repo, run_id)
    consume_agent_stage(repo, state, "tasks", outcome={})
    state = load_doc_state(repo, run_id)
    with patch("doc_loop.freeze_stage_artifact", side_effect=lambda _r, _s, stage: _verified_freeze(stage)):
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


# PRD 341 R33 — file-store review goldens must stay byte-identical after the
# issue-store facade lands. Locked relative to the plugin checkout root.
_FILE_STORE_REVIEW_GOLDENS: dict[str, str] = {
    "scripts/test/fixtures/persona-selection/minimal-standard.md": (
        "691a4c5889c0f6f846dff6b10c2e804d4a154ad5c8903718604cb262b12dae57"
    ),
    "scripts/test/fixtures/persona-selection/quick-tier.md": (
        "6b5f90012d9ea6e8238a30e55218c794b14f1f6523cf5556a9cd4861a252ab10"
    ),
    "scripts/test/fixtures/persona-selection/override-all.md": (
        "e0ce9ad30675bd864bbb1d00cfb2f01a388f4f04b4f1b2e42acbeb7bdbd89dfc"
    ),
    "scripts/test/fixtures/persona-selection/override-personas.md": (
        "c94bcc8055bb75044005de730d31f6728b24a59b528be1470f9e99604fcaff93"
    ),
    "scripts/test/fixtures/persona-selection/auth-signal.md": (
        "99aa3b442b2011b7c10b377e3f867bd8a47a984b7e7cdcbf2cbf72149bd3fad5"
    ),
    "scripts/test/fixtures/persona-selection/design-unambiguous.md": (
        "9c098b4224d811a582d05f07ce937f5a38dc83d7bdd39190f612ebade4c16fec"
    ),
    "core/skills/doc-review/references/findings-schema.json": (
        "3d62dd6d1efb37e9f6293b55e77c52030e8d4c36c738a53a0775888683cf0b4a"
    ),
}


def test_file_store_review_goldens_byte_identical() -> None:
    """R33: persona-selection fixtures + findings schema remain frozen."""
    root = Path(__file__).resolve().parents[3]
    for rel, expected in _FILE_STORE_REVIEW_GOLDENS.items():
        path = root / rel
        assert path.is_file(), f"missing file-store golden: {rel}"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == expected, f"file-store golden drift: {rel}"
