#!/usr/bin/env python3
"""Worktree integration barrier fixtures (PRD 271 R30)."""
from __future__ import annotations

import hashlib
import sys
import threading
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.execution_receipts import ExecutionReceiptJournal  # noqa: E402
from graph.resource_pools import ResourcePoolRegistry  # noqa: E402
from graph.scheduler import GraphScheduler, NodeExecutionResult  # noqa: E402
from graph.worktree_integration import (  # noqa: E402
    WorktreeCompletionManifest,
    WorktreeIntegrationBarrier,
    validate_manifest,
)


def _sha(label: str) -> str:
    return hashlib.sha1(label.encode()).hexdigest()


def _worktree_mutator(
    node_id: str,
    *,
    path: str,
    content_hash: str,
    gate: threading.Event | None = None,
) -> NodeExecutionResult:
    if gate is not None:
        gate.wait(timeout=2)
    return NodeExecutionResult(
        verdict="pass",
        output=node_id,
        duration_ms=1,
        coverage={
            "worktreeIntegration": {
                "baseSha": _sha("a"),
                "headSha": _sha(node_id),
                "headRef": f"refs/heads/{node_id}",
                "manifest": {path: content_hash},
                "verification": {"strategy": "mechanical", "passed": True},
            }
        },
    )


def _node(
    node_id: str,
    *,
    pool: str = "code-writers",
    write_scope: str = "worktree",
) -> dict[str, object]:
    return {
        "id": node_id,
        "kind": "command",
        "target": {"step": f"sw-{node_id}"},
        "resources": {"pool": pool, "slots": 1, "timeoutSeconds": 300},
        "isolation": {"mode": "worktree", "writeScope": write_scope},
        "execution": {"purity": "mutating", "cache": "disabled"},
        "verification": {"required": True, "strategy": "mechanical"},
    }


def _graph(
    nodes: list[dict[str, object]],
    edges: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "apiVersion": "shipwright.dev/v1alpha1",
        "kind": "WorkflowGraph",
        "metadata": {"name": "worktree-integration"},
        "spec": {
            "nodes": nodes,
            "edges": edges,
            "resourceLimits": {"maxConcurrency": 2, "maxDurationSeconds": 600},
            "verification": {"required": True, "failClosed": True},
        },
    }


def test_validate_manifest_requires_base_head_and_manifest() -> None:
    with pytest.raises(Exception, match="baseSha"):
        validate_manifest({"headSha": _sha("b"), "manifest": {"a": "1"}})
    manifest = validate_manifest(
        {
            "baseSha": _sha("a"),
            "headSha": _sha("b"),
            "manifest": {"src/a.py": "hash-a"},
            "verification": {"passed": True},
        }
    )
    assert manifest.base_sha == _sha("a")
    assert manifest.head_sha == _sha("b")


def test_worktree_integration_barrier_deterministic_order() -> None:
    source_order = {"left": 1, "right": 2}
    barrier = WorktreeIntegrationBarrier(source_order)
    barrier.enqueue(
        "right",
        WorktreeCompletionManifest(
            base_sha=_sha("a"),
            head_sha=_sha("r"),
            manifest={"shared.py": "hash-right"},
        ),
    )
    barrier.enqueue(
        "left",
        WorktreeCompletionManifest(
            base_sha=_sha("a"),
            head_sha=_sha("l"),
            manifest={"other.py": "hash-left"},
        ),
    )
    results = barrier.drain()
    assert [item.node_id for item in results] == ["left", "right"]
    assert all(item.verdict == "pass" for item in results)


def test_worktree_integration_barrier_conflict_terminal() -> None:
    barrier = WorktreeIntegrationBarrier({"first": 0, "second": 1})
    barrier.enqueue(
        "first",
        WorktreeCompletionManifest(
            base_sha=_sha("a"),
            head_sha=_sha("1"),
            manifest={"src/shared.py": "hash-a"},
        ),
    )
    barrier.enqueue(
        "second",
        WorktreeCompletionManifest(
            base_sha=_sha("a"),
            head_sha=_sha("2"),
            manifest={"src/shared.py": "hash-b"},
        ),
    )
    results = barrier.drain()
    assert results[0].verdict == "pass"
    assert results[1].verdict == "fail"
    assert results[1].conflict is True


def test_worktree_integration_barrier_two_siblings(tmp_path: Path) -> None:
    """R30: verifier admits only after both mutating siblings integrate."""
    start_gate = threading.Event()
    verifier_started = threading.Event()
    leases: dict[str, bool] = {"left": False, "right": False}

    def lease_releaser(node_id: str) -> None:
        leases[node_id] = True

    left_ready = threading.Event()
    right_ready = threading.Event()
    release_left = threading.Event()
    release_right = threading.Event()

    def execute(node: dict[str, object]) -> NodeExecutionResult:
        node_id = str(node["id"])
        if node_id == "left":
            left_ready.set()
            release_left.wait(timeout=2)
            return _worktree_mutator(
                node_id, path="src/a.py", content_hash="hash-left", gate=start_gate
            )
        if node_id == "right":
            right_ready.set()
            release_right.wait(timeout=2)
            return _worktree_mutator(
                node_id, path="src/b.py", content_hash="hash-right", gate=start_gate
            )
        if node_id == "verify":
            verifier_started.set()
            return NodeExecutionResult(verdict="pass", output="verified")
        raise AssertionError(f"unexpected node {node_id}")

    graph = _graph(
        [
            _node("left"),
            _node("right"),
            {
                **_node("verify", pool="read-only-reviewers", write_scope="read-only"),
                "execution": {"purity": "read-only", "cache": "disabled"},
                "isolation": {"mode": "process", "writeScope": "read-only"},
            },
        ],
        [
            {"from": "left", "to": "verify", "required": True},
            {"from": "right", "to": "verify", "required": True},
        ],
    )

    scheduler = GraphScheduler(
        execute,
        receipts=ExecutionReceiptJournal(tmp_path / "barrier"),
        pools=ResourcePoolRegistry.from_config(
            limits={"code-writers": 4, "read-only-reviewers": 4}
        ),
        lease_releaser=lease_releaser,
    )

    result_holder: list[object] = []
    error_holder: list[BaseException] = []

    def _run() -> None:
        try:
            result_holder.append(
                scheduler.run(graph, run_id="wt-r30", internal_only=True)
            )
        except BaseException as exc:
            error_holder.append(exc)

    runner = threading.Thread(target=_run, daemon=True)
    runner.start()

    assert left_ready.wait(timeout=2)
    assert right_ready.wait(timeout=2)
    assert not verifier_started.is_set()
    assert leases == {"left": False, "right": False}

    start_gate.set()
    release_left.set()
    release_right.set()
    runner.join(timeout=5)
    assert not error_holder, error_holder
    assert result_holder
    result = result_holder[0]
    assert result.verdict == "pass"
    assert leases["left"] is True
    assert leases["right"] is True
    assert verifier_started.is_set()
    verify_run = next(item for item in result.nodes if item.node_id == "verify")
    assert verify_run.verdict == "pass"


def test_worktree_integration_barrier_conflict_blocks_verifier(
    tmp_path: Path,
) -> None:
    verifier_started = threading.Event()

    def execute(node: dict[str, object]) -> NodeExecutionResult:
        node_id = str(node["id"])
        if node_id == "left":
            return _worktree_mutator(
                node_id, path="src/shared.py", content_hash="hash-left"
            )
        if node_id == "right":
            return _worktree_mutator(
                node_id, path="src/shared.py", content_hash="hash-right"
            )
        if node_id == "verify":
            verifier_started.set()
            return NodeExecutionResult(verdict="pass", output="verified")
        raise AssertionError(node_id)

    graph = _graph(
        [
            _node("left"),
            _node("right"),
            {
                **_node("verify", pool="read-only-reviewers", write_scope="read-only"),
                "execution": {"purity": "read-only", "cache": "disabled"},
                "isolation": {"mode": "process", "writeScope": "read-only"},
            },
        ],
        [
            {"from": "left", "to": "verify", "required": True},
            {"from": "right", "to": "verify", "required": True},
        ],
    )
    scheduler = GraphScheduler(
        execute,
        receipts=ExecutionReceiptJournal(tmp_path / "conflict"),
        pools=ResourcePoolRegistry.from_config(
            limits={"code-writers": 4, "read-only-reviewers": 4}
        ),
    )
    result = scheduler.run(graph, run_id="wt-conflict", internal_only=True)
    assert result.verdict == "fail"
    assert not verifier_started.is_set()
    right_run = next(item for item in result.nodes if item.node_id == "right")
    assert right_run.verdict == "fail"
    assert "conflict" in right_run.reason
