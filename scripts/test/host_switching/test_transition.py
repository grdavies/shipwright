"""PRD 352 phase 7.1 — transition state machine, lease fencing, digest validation (TR1–TR6)."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(REPO), str(REPO / "core"), str(REPO / "scripts")]

from adapters.host_resolver import QualifiedHost  # noqa: E402
from handoff.importer import validate_evidence_digests  # noqa: E402
from handoff.transition import (  # noqa: E402
    TRANSITION_SCHEMA_VERSION,
    TransitionError,
    advance_transition,
    create_transition,
    load_transition,
    persist_transition,
    record_observed_failure,
    transition_path,
)
from wave_lock import fence_source_lease, release_source_lease  # noqa: E402
from wave_state import adopt_run_lease  # noqa: E402


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def test_tr1_create_persists_requested_record(tmp_path: Path) -> None:
    record = create_transition(tmp_path, transition_id="tid-tr1", run_id="run-tr1")
    assert record["schemaVersion"] == TRANSITION_SCHEMA_VERSION
    assert record["state"] == "requested"
    assert transition_path(tmp_path, "tid-tr1").is_file()
    loaded = load_transition(tmp_path, "tid-tr1")
    assert loaded["runId"] == "run-tr1"


def test_tr2_adopt_run_lease_generation_fence() -> None:
    state: dict = {}
    adopt_run_lease(state, run_id="run-tr2", generation=1, ownership_generation=4)
    assert state["runLease"]["generation"] == 1
    assert state["runLease"]["ownershipGeneration"] == 4


def test_tr3_qualified_host_dataclass() -> None:
    host = QualifiedHost(
        host_id="cursor",
        surface_adapter="cursor",
        installed_version="2.15.0",
        capabilities={"deliver": True, "ship": True},
        auth_status="ok",
    )
    assert host.host_id == "cursor"
    assert host.surface_adapter == "cursor"
    assert host.capabilities["deliver"] is True


def test_tr5_schema_rejects_unknown_state(tmp_path: Path) -> None:
    create_transition(tmp_path, transition_id="tid-tr5", run_id="run-tr5")
    with pytest.raises(TransitionError) as exc:
        advance_transition(tmp_path, "tid-tr5", "not-a-state")
    assert exc.value.code == "transition_state_invalid"


def test_state_machine_ordered_progression(tmp_path: Path) -> None:
    create_transition(tmp_path, transition_id="tid-prog", run_id="run-prog")
    for state in ("checkpointed", "destination_validated", "ownership_transferred"):
        advance_transition(tmp_path, "tid-prog", state, ownership_generation=1)
    advance_transition(tmp_path, "tid-prog", "resumed")
    assert load_transition(tmp_path, "tid-prog")["state"] == "resumed"
    with pytest.raises(TransitionError) as exc:
        advance_transition(tmp_path, "tid-prog", "checkpointed")
    assert exc.value.code == "transition_not_allowed"


def test_crash_after_checkpoint_record_survives(tmp_path: Path) -> None:
    create_transition(tmp_path, transition_id="tid-crash", run_id="run-crash")
    advance_transition(tmp_path, "tid-crash", "checkpointed")
    path = transition_path(tmp_path, "tid-crash")
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["state"] == "checkpointed"
    reloaded = load_transition(tmp_path, "tid-crash")
    assert reloaded["state"] == "checkpointed"
    advance_transition(tmp_path, "tid-crash", "destination_validated")
    assert load_transition(tmp_path, "tid-crash")["state"] == "destination_validated"


def test_lease_fencing_blocks_foreign_session(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    first = fence_source_lease(tmp_path, "run-fence", "sess-a", transition_id="tid-fence")
    assert first["verdict"] == "pass"
    blocked = fence_source_lease(tmp_path, "run-fence", "sess-b", transition_id="tid-fence")
    assert blocked["verdict"] == "fail"
    released = release_source_lease(tmp_path, "run-fence", "sess-a")
    assert released["verdict"] == "pass"


def test_digest_validation_pass_and_stale(tmp_path: Path) -> None:
    evidence = tmp_path / "gate.txt"
    evidence.write_text("ok\n", encoding="utf-8")
    digest = _sha256_file(evidence)
    passed = validate_evidence_digests(tmp_path, [{"path": "gate.txt", "digest": digest}])
    assert passed["verdict"] == "pass"
    stale = validate_evidence_digests(
        tmp_path, [{"path": "gate.txt", "digest": "sha256:" + ("0" * 64)}]
    )
    assert stale["verdict"] == "fail"
    assert stale["issues"][0]["code"] == "evidence_digest_mismatch"
    assert stale["rerunChecks"] == ["gate.txt"]


def test_observed_failure_rejects_fabrication(tmp_path: Path) -> None:
    create_transition(tmp_path, transition_id="tid-fail", run_id="run-fail")
    with pytest.raises(TransitionError) as exc:
        record_observed_failure(
            tmp_path,
            "tid-fail",
            {"code": "quota", "remainingAllowance": 12},
        )
    assert exc.value.code == "transition_failure_fabrication"
    record_observed_failure(
        tmp_path,
        "tid-fail",
        {"code": "quota:exhausted", "message": "rate limited", "source": "observed"},
    )
    record = load_transition(tmp_path, "tid-fail")
    assert record["spendingObservation"]["code"] == "quota:exhausted"
    assert "remainingAllowance" not in record["spendingObservation"]


def test_persist_before_announce_round_trip(tmp_path: Path) -> None:
    record = create_transition(tmp_path, transition_id="tid-persist", run_id="run-persist")
    record["state"] = "waiting"
    persist_transition(tmp_path, record)
    assert load_transition(tmp_path, "tid-persist")["state"] == "waiting"
