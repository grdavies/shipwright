"""PRD 352 phase 5 — evidence digests, uncommitted checkpoint, receipt reconciliation (R26–R29)."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "core"), str(REPO / "scripts")]

from handoff.bundle import (  # noqa: E402
    UNCOMMITTED_POLICY_PRESERVE,
    UNCOMMITTED_POLICY_REQUIRE_DISCARD,
    capture_uncommitted_changes_checkpoint,
    read_uncommitted_changes_checkpoint,
    resolve_uncommitted_changes_policy,
    worktree_has_uncommitted_changes,
)
from handoff.importer import validate_evidence_digests, validate_evidence_on_resume  # noqa: E402
from wave_deliver_loop import reconcile_receipts_before_retry  # noqa: E402
from wave_state import mark_in_flight_uncertain  # noqa: E402
from wave_transition_receipt import read_receipt  # noqa: E402


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"sha256:{digest}"


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "shipwright-test@localhost"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    (path / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)


def test_validate_evidence_digests_pass(tmp_path: Path) -> None:
    evidence = tmp_path / "notes.md"
    evidence.write_text("ok\n", encoding="utf-8")
    refs = [{"path": "notes.md", "digest": _sha256_file(evidence)}]
    out = validate_evidence_digests(tmp_path, refs)
    assert out["verdict"] == "pass"
    assert out["checked"] == 1
    assert out["rerunChecks"] == []


def test_validate_evidence_digests_missing_explains_and_reruns_minimal(tmp_path: Path) -> None:
    refs = [{"path": "missing.md", "digest": "sha256:" + ("a" * 64)}]
    out = validate_evidence_digests(tmp_path, refs)
    assert out["verdict"] == "fail"
    assert out["issues"][0]["code"] == "evidence_missing"
    assert out["rerunChecks"] == ["missing.md"]
    assert "Restore evidence file" in out["issues"][0]["recovery"]


def test_validate_evidence_on_resume_from_import_record(tmp_path: Path) -> None:
    evidence = tmp_path / "gate.txt"
    evidence.write_text("pass\n", encoding="utf-8")
    record = {
        "evidence": [{"path": "gate.txt", "digest": _sha256_file(evidence)}],
        "continuation_payload": {"evidenceReferences": []},
    }
    out = validate_evidence_on_resume(tmp_path, record)
    assert out["verdict"] == "pass"


def test_uncommitted_checkpoint_preserves_dirty_worktree(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    dirty = tmp_path / "dirty.txt"
    dirty.write_text("wip\n", encoding="utf-8")
    assert worktree_has_uncommitted_changes(tmp_path)
    out = capture_uncommitted_changes_checkpoint(tmp_path, "tid-dirty", policy=UNCOMMITTED_POLICY_PRESERVE)
    assert out["verdict"] == "pass"
    assert out["patchBytes"] > 0
    stored = read_uncommitted_changes_checkpoint(tmp_path, "tid-dirty")
    assert stored and stored["status"] == "preserved"
    assert "dirty.txt" in stored["porcelain"]


def test_uncommitted_policy_requires_explicit_discard(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    (tmp_path / "wip.txt").write_text("x\n", encoding="utf-8")
    out = resolve_uncommitted_changes_policy(
        tmp_path,
        "tid-halt",
        policy=UNCOMMITTED_POLICY_REQUIRE_DISCARD,
        confirm_discard=False,
    )
    assert out["verdict"] == "halt"
    assert out["error"] == "handoff:uncommitted-changes-require-discard"


def test_reconcile_receipts_reconstructs_from_remote_commit(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    branch_tip = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    run_id = "run-reconcile"
    state: dict = {}
    mark_in_flight_uncertain(
        state,
        "phase-ship:commit",
        reason="no-local-receipt",
        externalOp={
            "kind": "commit",
            "idempotencyKey": "commit-phase-ship",
            "identity": {"branch": "HEAD", "commitSha": branch_tip},
        },
    )
    out = reconcile_receipts_before_retry(tmp_path, state, run_id)
    assert out["verdict"] == "pass"
    assert out["reconciledCount"] >= 1
    assert any(item.get("action") == "receipt-reconstructed" for item in out["reconciled"])
    receipt = read_receipt(tmp_path, run_id, "commit-phase-ship")
    assert receipt is not None
    assert receipt.get("status") == "complete"
    assert receipt.get("externalMutation", {}).get("remoteState", {}).get("commit")


def test_reconcile_absence_of_receipt_checks_remote_not_assumed_never_happened(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    state: dict = {}
    mark_in_flight_uncertain(
        state,
        "phase-ship:pr",
        reason="no-local-receipt",
        externalOp={
            "kind": "pr-create",
            "idempotencyKey": "pr-missing",
            "identity": {"head": "feat/nonexistent-branch-xyz"},
        },
    )
    out = reconcile_receipts_before_retry(tmp_path, state, "run-pr")
    remote_items = [item for item in out["reconciled"] if item.get("action") == "remote-not-observed"]
    assert remote_items
    assert remote_items[0]["note"] == "absence-of-receipt-does-not-prove-never-happened"
