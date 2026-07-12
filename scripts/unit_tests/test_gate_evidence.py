"""Unit tests for gate evidence schema, resolver, and binding modes (PRD 065 R7, R21, R22)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from gate_evidence import (
    attach_provenance_marker,
    build_evidence_record,
    compute_tree_hash,
    evidence_dir,
    evidence_record_path,
    read_record_file,
    resolve_authoritative_record,
    validate_outcome_path_non_overlap,
    validate_provenance_marker,
    write_evidence_atomic,
)


def _sample_execution() -> dict:
    return {
        "argv": ["python3", "scripts/example.py"],
        "exitCode": 0,
        "stdoutDigest": "a" * 64,
        "stderrDigest": "b" * 64,
        "duration": 0.12,
    }


def test_tree_stable_vs_head_exact_binding(repo_root: Path, tmp_path: Path) -> None:
    phase = "evidence-record-schema-resolver-and-binding-modes-r7-r21-r22"
    root = repo_root
    head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    tree = compute_tree_hash(root)

    tree_record = build_evidence_record(
        gate_id="build-chain",
        gate_class="mandatory",
        binding_mode="tree-stable",
        evaluation_point="pre-sw-commit",
        verdict="pass",
        execution=_sample_execution(),
        root=root,
        head_sha=head,
        tree_hash=tree,
    )
    tree_path = evidence_record_path(root, phase, "build-chain")
    write_evidence_atomic(tree_path, tree_record)

    head_record = build_evidence_record(
        gate_id="pre-pr-smoke",
        gate_class="mandatory",
        binding_mode="head-exact",
        evaluation_point="pre-sw-pr",
        verdict="pass",
        execution=_sample_execution(),
        root=root,
        head_sha=head,
        tree_hash=tree,
    )
    head_path = evidence_record_path(root, phase, "pre-pr-smoke")
    write_evidence_atomic(head_path, head_record)

    resolved_tree, _ = resolve_authoritative_record(root, phase, "build-chain")
    resolved_head, _ = resolve_authoritative_record(root, phase, "pre-pr-smoke")
    assert resolved_tree is not None
    assert resolved_head is not None
    assert resolved_tree["bindingMode"] == "tree-stable"
    assert resolved_head["bindingMode"] == "head-exact"

    stale_head = dict(head_record)
    stale_head["headSha"] = "0" * 40
    stale_head = attach_provenance_marker(stale_head)
    write_evidence_atomic(head_path, stale_head)
    stale_resolved, cause = resolve_authoritative_record(root, phase, "pre-pr-smoke")
    assert stale_resolved is None
    assert cause == "gate-evidence:head-mismatch"


def test_partial_file_fail_closed(repo_root: Path, tmp_path: Path) -> None:
    phase = "evidence-record-schema-resolver-and-binding-modes-r7-r21-r22"
    path = evidence_record_path(repo_root, phase, "verification-gate")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"gateId": "verification-gate", "truncated": true\n', encoding="utf-8")
    record, cause = read_record_file(path)
    assert record is None
    assert cause == "gate-evidence:partial"


def test_forged_provenance_fail_closed(repo_root: Path) -> None:
    phase = "evidence-record-schema-resolver-and-binding-modes-r7-r21-r22"
    record = build_evidence_record(
        gate_id="verification-gate",
        gate_class="mandatory",
        binding_mode="head-exact",
        evaluation_point="pre-sw-commit",
        verdict="pass",
        execution=_sample_execution(),
        root=repo_root,
    )
    stamped = attach_provenance_marker(record)
    stamped["provenanceMarker"] = "f" * 64
    path = evidence_record_path(repo_root, phase, "verification-gate")
    write_evidence_atomic(path, stamped)
    # Re-read bypassing write's re-attach by writing raw forged marker
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["provenanceMarker"] = "f" * 64
    path.write_text(json.dumps(raw) + "\n", encoding="utf-8")
    record, cause = read_record_file(path)
    assert record is None
    assert cause == "gate-evidence:forged-provenance"


def test_evidence_dir_overlap_denied(repo_root: Path) -> None:
    phase = "evidence-record-schema-resolver-and-binding-modes-r7-r21-r22"
    ev_dir = evidence_dir(repo_root, phase)
    outcome = ev_dir / "nested" / "outcome.json"
    ok, cause = validate_outcome_path_non_overlap(outcome, ev_dir)
    assert ok is False
    assert cause == "gate-evidence:outcome-overlap"

    outside = repo_root / ".cursor" / "sw-deliver-runs" / phase / "agent-outcome.json"
    ok2, cause2 = validate_outcome_path_non_overlap(outside, ev_dir)
    assert ok2 is True
    assert cause2 is None


def test_unknown_gate_id_inert(repo_root: Path) -> None:
    phase = "evidence-record-schema-resolver-and-binding-modes-r7-r21-r22"
    record, cause = resolve_authoritative_record(repo_root, phase, "not-a-real-gate-id")
    assert record is None
    assert cause is None


def test_provenance_marker_roundtrip(repo_root: Path) -> None:
    record = build_evidence_record(
        gate_id="behavioral-anomaly",
        gate_class="mandatory",
        binding_mode="head-exact",
        evaluation_point="post-sw-verify",
        verdict="pass",
        execution=_sample_execution(),
        root=repo_root,
    )
    stamped = attach_provenance_marker(record)
    ok, cause = validate_provenance_marker(stamped)
    assert ok is True
    assert cause is None

