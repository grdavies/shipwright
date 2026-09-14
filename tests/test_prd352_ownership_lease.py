"""PRD 352 Slice 2 — execution ownership and lease fencing (R5–R8, R17–R21, TR5)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "core"), str(REPO / "scripts")]

from handoff.importer import ImportLock, write_resume_evidence  # noqa: E402
from handoff.transition import (  # noqa: E402
    TransitionError,
    advance_transition,
    create_transition,
    load_transition,
    transition_path,
    transitions_dir,
)
from shipwright_paths import destination_ack_path, resume_evidence_path, run_dir  # noqa: E402
from wave_lock import (  # noqa: E402
    acquire_run_lease,
    fence_source_lease,
    release_source_lease,
    status_run_lease,
)
from wave_state import (  # noqa: E402
    adopt_run_lease,
    assert_ownership_before_dispatch,
    mark_in_flight_uncertain,
    reconcile_uncertain_in_flight,
)
from wave_deliver_loop import assert_handoff_resume_not_duplicate  # noqa: E402


def test_adopt_run_lease_ownership_generation() -> None:
    state: dict = {}
    adopt_run_lease(state, run_id="run-1", generation=2, ownership_generation=3)
    assert state["runLease"]["generation"] == 2
    assert state["runLease"]["ownershipGeneration"] == 3


def test_assert_ownership_before_dispatch_stale() -> None:
    state = {"runLease": {"ownershipGeneration": 2, "sessionId": "sess-a"}}
    with pytest.raises(SystemExit):
        assert_ownership_before_dispatch(state, 1)


def test_fence_and_release_source_lease(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    out = fence_source_lease(tmp_path, "run-1", "sess-src", transition_id="tid-1")
    assert out["verdict"] == "pass"
    blocked = fence_source_lease(tmp_path, "run-1", "sess-other", transition_id="tid-1")
    assert blocked["verdict"] == "fail"
    released = release_source_lease(tmp_path, "run-1", "sess-src")
    assert released["verdict"] == "pass"
    again = fence_source_lease(tmp_path, "run-1", "sess-other", transition_id="tid-1")
    assert again["verdict"] == "pass"


def test_import_lock_covers_ownership_transfer(tmp_path: Path) -> None:
    lock = ImportLock(tmp_path, "run-1", agent_identity="agent-a")
    lock.acquire(phase="validation")
    lock.enter_ownership_transfer()
    meta = json.loads(lock.path.read_text(encoding="utf-8"))
    assert meta["phase"] == "ownership_transfer"
    lock.release()
    assert not lock.path.is_file()


def test_transition_state_machine_persists_before_announce(tmp_path: Path) -> None:
    create_transition(tmp_path, transition_id="tid-1", run_id="run-1", session_id="sess-1")
    path = transition_path(tmp_path, "tid-1")
    assert path.is_file()
    advance_transition(tmp_path, "tid-1", "checkpointed")
    advance_transition(tmp_path, "tid-1", "destination_validated")
    advance_transition(tmp_path, "tid-1", "ownership_transferred", ownership_generation=1)
    advance_transition(tmp_path, "tid-1", "resumed")
    record = load_transition(tmp_path, "tid-1")
    assert record["state"] == "resumed"
    assert record["ownershipGeneration"] == 1


def test_transition_schema_file_present() -> None:
    schema = REPO / "core" / "sw-reference" / "handoff-transition.schema.json"
    assert schema.is_file()
    doc = json.loads(schema.read_text(encoding="utf-8"))
    assert doc["title"] == "HandoffTransition@v1"
    assert transitions_dir(REPO).name == "sw-handoff-transitions"


def test_resume_evidence_distinct_from_import_ack(tmp_path: Path) -> None:
    run_id = "run-ev"
    transition_id = "tid-ev"
    ack_path = destination_ack_path(tmp_path, run_id, transition_id)
    ack_path.parent.mkdir(parents=True, exist_ok=True)
    ack_path.write_text(
        json.dumps({"hostAdapterId": "dest", "importedAt": "2026-09-14T00:00:00Z"}) + "\n",
        encoding="utf-8",
    )
    evidence = write_resume_evidence(
        tmp_path,
        run_id=run_id,
        transition_id=transition_id,
        next_eligible_action="deliver-loop",
        host_adapter_id="dest",
    )
    assert evidence["nextEligibleAction"] == "deliver-loop"
    assert resume_evidence_path(tmp_path, run_id, transition_id).is_file()
    assert ack_path.is_file()
    import_record_path = run_dir(tmp_path, run_id) / "imports" / f"{transition_id}.json"
    import_record_path.parent.mkdir(parents=True, exist_ok=True)
    import_record_path.write_text(
        json.dumps({"transition_id": transition_id, "run_id": run_id}) + "\n",
        encoding="utf-8",
    )
    write_resume_evidence(
        tmp_path,
        run_id=run_id,
        transition_id=transition_id,
        next_eligible_action="deliver-loop",
        host_adapter_id="dest",
    )
    import_record = json.loads(import_record_path.read_text(encoding="utf-8"))
    assert import_record.get("resumeEvidence")


def test_mark_and_reconcile_uncertain_in_flight() -> None:
    state: dict = {}
    mark_in_flight_uncertain(state, "phase-ship", reason="no-result")
    assert state["uncertainInFlight"]["phase-ship"]["status"] == "uncertain"
    reconciled = reconcile_uncertain_in_flight(state)
    assert reconciled and reconciled[0]["workId"] == "phase-ship"
    assert state["uncertainInFlight"] == {}


def test_duplicate_dispatch_halt_when_foreign_lease(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.setenv("SW_SESSION_ID", "sess-caller")
    acquired = acquire_run_lease(tmp_path, "run-dup")
    assert acquired["verdict"] == "pass"
    status = status_run_lease(tmp_path, "run-dup")
    meta = status["meta"]
    meta["sessionId"] = "sess-owner"
    lock_path = Path(status["lockPath"])
    lock_path.write_text(json.dumps(meta) + "\n", encoding="utf-8")
    duplicate = assert_handoff_resume_not_duplicate(tmp_path, "run-dup", session_id="sess-caller")
    assert duplicate is not None
    assert duplicate["error"] == "handoff:duplicate-dispatch"
    assert duplicate["ownerSessionId"] == "sess-owner"


def test_invalid_transition_raises(tmp_path: Path) -> None:
    create_transition(tmp_path, transition_id="tid-x", run_id="run-x")
    with pytest.raises(TransitionError):
        advance_transition(tmp_path, "tid-x", "resumed")
