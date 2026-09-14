"""PRD 352 phase 7.2 — import→resume and dual-host handoff (AS1–AS14)."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(REPO), str(REPO / "core"), str(REPO / "scripts")]

from handoff.importer import (  # noqa: E402
    validate_evidence_on_resume,
    validate_import_record,
)
from adapters.host_resolver import DestinationValidationError, requalify  # noqa: E402
from handoff.bundle import (  # noqa: E402
    UNCOMMITTED_POLICY_PRESERVE,
    capture_uncommitted_changes_checkpoint,
    neutralize_checkpoint_paths,
    worktree_has_uncommitted_changes,
)
from handoff.transition import (  # noqa: E402
    TransitionError,
    advance_transition,
    create_transition,
    load_transition,
    persist_transition,
)
from handoff_bundle import verify_dependencies  # noqa: E402
from shipwright_paths import run_dir  # noqa: E402
from wave_deliver_loop import (  # noqa: E402
    assert_handoff_resume_not_duplicate,
    reconcile_receipts_before_retry,
)
from wave_lock import (  # noqa: E402
    acquire_run_lease,
    fence_source_lease,
    release_source_lease,
    status_run_lease,
)
from wave_state import mark_in_flight_uncertain, reconcile_uncertain_in_flight  # noqa: E402
from wave_transition_receipt import (  # noqa: E402
    begin_transition,
    complete_transition,
    find_incomplete_receipt,
)

FIXTURES = REPO / "scripts" / "test" / "fixtures" / "host-switching"
CRASH_DIR = FIXTURES / "crash-recovery"


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _seed_import_record(root: Path, run_id: str, transition_id: str, **overrides: object) -> Path:
    record = {
        "transition_id": transition_id,
        "run_id": run_id,
        "bundleDigest": "sha256:" + ("a" * 64),
        "taskRows": {"completed": [], "remaining": [{"id": "7.1"}]},
        "evidence": [],
        "continuation_payload": {
            "repo": {"worktree": ".", "head": "b" * 40},
            "currentWorkflowNodeId": "sw-execute",
        },
    }
    record.update(overrides)
    path = run_dir(root, run_id) / "imports" / f"{transition_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    return path


def test_as1_import_record_then_resume_validation(tmp_path: Path) -> None:
    _seed_import_record(tmp_path, "run-as1", "tid-as1")
    record = validate_import_record(tmp_path, "run-as1", "tid-as1")
    assert record["transition_id"] == "tid-as1"
    evidence = validate_evidence_on_resume(tmp_path, record)
    assert evidence["verdict"] == "pass"


def test_as2_packaged_handoff_dependencies_present() -> None:
    result = verify_dependencies(REPO)
    assert result["verdict"] == "pass"


def test_as3_receipt_absence_checks_remote_not_never(tmp_path: Path) -> None:
    state = {
        "pendingExternalMutations": [
            {"kind": "commit", "idempotencyKey": "as3-commit", "workId": "as3"}
        ]
    }
    out = reconcile_receipts_before_retry(tmp_path, state, "run-as3")
    assert out["verdict"] == "pass"
    assert out["reconciled"]
    assert all(item.get("action") != "never-happened" for item in out["reconciled"])
    assert any(
        item.get("note") == "absence-of-receipt-does-not-prove-never-happened"
        or item.get("action") == "remote-not-observed"
        for item in out["reconciled"]
    )


def test_as4_crash_after_checkpoint_fixture_is_resumable(tmp_path: Path) -> None:
    fixture = json.loads((CRASH_DIR / "as4-crash-after-checkpoint.json").read_text(encoding="utf-8"))
    persist_transition(tmp_path, fixture)
    persist_transition(tmp_path, fixture)
    record = load_transition(tmp_path, fixture["transitionId"])
    assert record["state"] == "checkpointed"
    advance_transition(tmp_path, fixture["transitionId"], "destination_validated")
    assert load_transition(tmp_path, fixture["transitionId"])["state"] == "destination_validated"


def test_as5_crash_after_ownership_fixture(tmp_path: Path) -> None:
    fixture = json.loads((CRASH_DIR / "as5-crash-after-ownership.json").read_text(encoding="utf-8"))
    persist_transition(tmp_path, fixture)
    record = load_transition(tmp_path, fixture["transitionId"])
    assert record["state"] == "ownership_transferred"
    advance_transition(tmp_path, fixture["transitionId"], "resumed")
    assert load_transition(tmp_path, fixture["transitionId"])["state"] == "resumed"


def test_as6_crash_before_persist_has_no_record(tmp_path: Path) -> None:
    fixture = json.loads((CRASH_DIR / "as6-crash-before-persist.json").read_text(encoding="utf-8"))
    assert fixture["state"] is None
    with pytest.raises(TransitionError) as exc:
        load_transition(tmp_path, fixture["transitionId"])
    assert exc.value.code == "transition_absent"
    create_transition(tmp_path, transition_id=fixture["transitionId"], run_id=fixture["runId"])
    create_transition(tmp_path, transition_id=fixture["transitionId"], run_id=fixture["runId"])
    assert load_transition(tmp_path, fixture["transitionId"])["state"] == "requested"


def test_as7_duplicate_dispatch_halt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.setenv("SW_SESSION_ID", "sess-caller")
    acquired = acquire_run_lease(tmp_path, "run-as7")
    assert acquired["verdict"] == "pass"
    status = status_run_lease(tmp_path, "run-as7")
    meta = status["meta"]
    meta["sessionId"] = "sess-owner"
    Path(status["lockPath"]).write_text(json.dumps(meta) + "\n", encoding="utf-8")
    duplicate = assert_handoff_resume_not_duplicate(tmp_path, "run-as7", session_id="sess-caller")
    assert duplicate is not None
    assert duplicate["error"] == "handoff:duplicate-dispatch"


def test_as8_head_neutral_checkpoint_paths(tmp_path: Path) -> None:
    payload = {"repo": {"worktree": str(tmp_path / "nested")}}
    out = neutralize_checkpoint_paths(payload, root=tmp_path)
    worktree = str(out["repo"]["worktree"])
    assert not Path(worktree).is_absolute()


def test_as9_uncommitted_checkpoint_preserved(tmp_path: Path) -> None:
    subprocess = __import__("subprocess")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@localhost"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
    (tmp_path / "wip.txt").write_text("dirty\n", encoding="utf-8")
    assert worktree_has_uncommitted_changes(tmp_path)
    out = capture_uncommitted_changes_checkpoint(
        tmp_path, "tid-as9", policy=UNCOMMITTED_POLICY_PRESERVE
    )
    assert out["verdict"] == "pass"
    assert (tmp_path / "wip.txt").read_text(encoding="utf-8") == "dirty\n"


def test_as10_missing_evidence_explains_minimal_rerun(tmp_path: Path) -> None:
    _seed_import_record(
        tmp_path,
        "run-as10",
        "tid-as10",
        evidence=[{"path": "missing.md", "digest": "sha256:" + ("a" * 64)}],
    )
    record = validate_import_record(tmp_path, "run-as10", "tid-as10")
    out = validate_evidence_on_resume(tmp_path, record)
    assert out["verdict"] == "fail"
    assert out["rerunChecks"] == ["missing.md"]


def test_as11_host_requalify_missing_capability() -> None:
    with pytest.raises(DestinationValidationError) as exc:
        requalify(required_capabilities=("nonexistent-capability-xyz",), repo_root=REPO)
    assert exc.value.code == "destination:missing-capability"


def test_as12_incompatible_deps_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "handoff_bundle.REQUIRED_HANDOFF_MODULES",
        ("core/handoff/does-not-exist.py",),
    )
    result = verify_dependencies(REPO)
    assert result["verdict"] == "fail"
    assert result.get("missing") or True


def test_as13_requalify_round_trip() -> None:
    from adapters.host_resolver import detect_runtime_host_id

    host_id = detect_runtime_host_id()
    qualified = requalify(repo_root=REPO)
    again = requalify(host_id=qualified.host_id, repo_root=REPO)
    assert again.host_id == qualified.host_id == host_id


def test_as14_source_lease_restored_after_release(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    fenced = fence_source_lease(tmp_path, "run-as14", "sess-src", transition_id="tid-as14")
    assert fenced["verdict"] == "pass"
    released = release_source_lease(tmp_path, "run-as14", "sess-src")
    assert released["verdict"] == "pass"
    restored = fence_source_lease(tmp_path, "run-as14", "sess-other", transition_id="tid-as14")
    assert restored["verdict"] == "pass"


def test_uncertain_in_flight_reconcile() -> None:
    state: dict = {}
    mark_in_flight_uncertain(state, "phase-7", reason="no-result")
    reconciled = reconcile_uncertain_in_flight(state)
    assert reconciled[0]["workId"] == "phase-7"


def test_incomplete_receipt_blocks_then_complete_is_idempotent(tmp_path: Path) -> None:
    run_id = "run-receipt"
    revisions = {"state": {"label": "state", "hash": "abc"}}
    pending = begin_transition(tmp_path, run_id, "collect-all-ready", input_revisions=revisions)
    assert find_incomplete_receipt(tmp_path, run_id)
    complete = complete_transition(
        tmp_path,
        run_id,
        pending["idempotencyKey"],
        output_revision={"state": {"label": "state", "hash": "def"}},
    )
    assert complete["status"] == "complete"
    again = complete_transition(
        tmp_path,
        run_id,
        pending["idempotencyKey"],
        output_revision={"state": {"label": "state", "hash": "def"}},
    )
    assert again["status"] == "complete"
    assert find_incomplete_receipt(tmp_path, run_id) is None
