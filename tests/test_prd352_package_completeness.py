"""PRD 352 Slice 1 phase 4 — package completeness + durable checkpoint (R14, R16)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "core"), str(REPO / "scripts")]

from build_dist import build_dist, verify_handoff_release_gate  # noqa: E402
from handoff.bundle import (  # noqa: E402
    build_continuation_payload,
    durable_checkpoint_path,
    export_cross_host_bundle,
    read_durable_checkpoint,
    write_durable_checkpoint,
)
from handoff.validate_bundle import digest_payload  # noqa: E402
from runtime_requirements import HANDOFF_RUNTIME_MODULES, sync_handoff_runtime_modules  # noqa: E402


FIXTURE = REPO / "core" / "tests" / "fixtures" / "bundle_self_test" / "pass.json"


def _base_bundle() -> dict:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data.pop("bundleDigest", None)
    data["bundleDigest"] = digest_payload(data)
    return data


def test_sync_handoff_runtime_modules_mirrors_under_sw() -> None:
    result = sync_handoff_runtime_modules(REPO)
    assert result["verdict"] == "pass"
    for rel in HANDOFF_RUNTIME_MODULES:
        mirrored = REPO / "sw" / rel
        assert mirrored.is_file(), rel


def test_build_dist_handoff_release_gate_passes() -> None:
    gate = verify_handoff_release_gate(REPO)
    assert gate["verdict"] == "pass"
    assert (REPO / "dist" / "manifest.json").is_file()


def test_build_dist_fails_when_handoff_module_missing(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "dist" / "cursor").mkdir(parents=True)
    (tmp_path / "dist" / "cursor" / "documentation").mkdir(parents=True)
    (tmp_path / "version.txt").write_text("0.0.0\n", encoding="utf-8")
    result = build_dist(tmp_path, skip_generate=True, sync_runtime=False, build_wheel_flag=False)
    assert result["verdict"] == "error"
    assert "handoff" in str(result.get("error") or "").lower() or result.get("missing")


def test_write_durable_checkpoint_before_bundle_export(tmp_path: Path) -> None:
    base = _base_bundle()
    cont = build_continuation_payload(
        task_baseline={"unitId": "352-reliable-host-switching", "canonicalVersion": "1"},
        prd_baseline={"frozenCanonicalVersion": "1"},
        repo={"worktree": str(tmp_path), "head": "d" * 40},
        current_workflow_node_id="sw-execute",
        completed_task_rows=[],
        remaining_task_rows=[{"id": "4.2"}],
        unresolved_decisions=[],
        evidence_references=[],
        model_attempt_lineage=[],
    )
    transition_id = "33333333-3333-3333-3333-333333333333"
    out = tmp_path / "bundle.json"

    export_cross_host_bundle(
        base,
        out,
        source_host="claude-code",
        destination_host="codex",
        continuation_payload=cont,
        transition_id=transition_id,
        root=tmp_path,
    )

    checkpoint = durable_checkpoint_path(tmp_path, transition_id)
    assert checkpoint.is_file()
    loaded = read_durable_checkpoint(tmp_path, transition_id)
    assert loaded["status"] == "checkpointed"
    assert loaded["continuationPayload"]["repo"]["worktree"] == "."
    assert out.is_file()


def test_durable_checkpoint_written_without_waiting_for_completion(tmp_path: Path) -> None:
    payload = {
        "repo": {"worktree": ".", "head": "e" * 40},
        "currentWorkflowNodeId": "sw-verify",
    }
    transition_id = "44444444-4444-4444-4444-444444444444"
    result = write_durable_checkpoint(
        tmp_path,
        transition_id=transition_id,
        continuation_payload=payload,
        bundle_digest="sha256:" + ("f" * 64),
        source_host="cursor",
        destination_host="claude-code",
    )
    assert result["verdict"] == "pass"
    assert read_durable_checkpoint(tmp_path, transition_id)["bundleDigest"].startswith("sha256:")


def test_read_durable_checkpoint_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="missing"):
        read_durable_checkpoint(tmp_path, "missing-transition")
