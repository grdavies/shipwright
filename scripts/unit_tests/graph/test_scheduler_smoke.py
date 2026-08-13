#!/usr/bin/env python3
"""Runtime scheduler smoke fixtures."""
from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.execution_receipts import ExecutionReceiptJournal  # noqa: E402
from graph.kernel_compiler import KernelCompilationError  # noqa: E402
from graph.resource_pools import ResourcePoolRegistry  # noqa: E402
from graph.scheduler import (  # noqa: E402
    GraphScheduler,
    InternalSchedulerDisabled,
    NodeExecutionResult,
)


def _node(node_id: str, *, pool: str = "code-writers") -> dict[str, object]:
    return {
        "id": node_id,
        "kind": "command",
        "target": {"step": f"sw-{node_id}"},
        "resources": {
            "pool": pool,
            "slots": 1,
            "timeoutSeconds": 300,
        },
        "isolation": {"mode": "worktree", "writeScope": "worktree"},
        "verification": {"required": True, "strategy": "mechanical"},
    }


def valid_graph() -> dict[str, object]:
    return {
        "apiVersion": "shipwright.dev/v1alpha1",
        "kind": "WorkflowGraph",
        "metadata": {"name": "scheduler-smoke"},
        "spec": {
            "nodes": [
                _node("prepare"),
                _node("verify", pool="read-only-reviewers"),
            ],
            "edges": [{"from": "prepare", "to": "verify", "required": True}],
            "resourceLimits": {
                "maxConcurrency": 2,
                "maxDurationSeconds": 600,
            },
            "verification": {"required": True, "failClosed": True},
        },
    }


def test_internal_scheduler_executes_graph_and_records_receipts(tmp_path: Path) -> None:
    dispatched: list[str] = []

    def execute(node: dict[str, object]) -> NodeExecutionResult:
        dispatched.append(str(node["id"]))
        return NodeExecutionResult(
            verdict="pass",
            output={"node": node["id"]},
            model="fixture",
            tokens=7,
            duration_ms=3,
        )

    journal = ExecutionReceiptJournal(tmp_path / "receipts")
    pools = ResourcePoolRegistry.from_config(
        limits={"code-writers": 1, "read-only-reviewers": 1}
    )
    scheduler = GraphScheduler(execute, receipts=journal, pools=pools)

    with pytest.raises(InternalSchedulerDisabled):
        scheduler.run(valid_graph(), run_id="public-attempt")
    assert dispatched == []

    result = scheduler.run(
        valid_graph(),
        run_id="internal-smoke",
        internal_only=True,
        write_paths={
            "prepare": {"build/output.json"},
            "verify": set(),
        },
    )

    assert result.verdict == "pass"
    assert [node.node_id for node in result.nodes] == ["prepare", "verify"]
    assert dispatched == ["prepare", "verify"]
    assert len(journal.list_receipts()) == 2
    assert all(receipt["state"] == "complete" for receipt in result.receipts)
    assert pools.snapshot()["code-writers"]["inUse"] == 0
    assert pools.snapshot()["read-only-reviewers"]["inUse"] == 0

    replay = scheduler.run(
        valid_graph(),
        run_id="internal-smoke",
        internal_only=True,
    )
    assert replay.verdict == "pass"
    assert dispatched == ["prepare", "verify"]
    assert all(not node.dispatched for node in replay.nodes)
    assert len(journal.list_receipts()) == 2


def test_kernel_rejected_graph_is_never_dispatched(tmp_path: Path) -> None:
    graph = deepcopy(valid_graph())
    graph["spec"]["nodes"][0]["kind"] = "untrusted-runtime-code"
    dispatched: list[str] = []

    def execute(node: dict[str, object]) -> NodeExecutionResult:
        dispatched.append(str(node["id"]))
        return NodeExecutionResult(verdict="pass")

    scheduler = GraphScheduler(
        execute,
        receipts=ExecutionReceiptJournal(tmp_path / "receipts"),
        pools=ResourcePoolRegistry(),
    )

    with pytest.raises(KernelCompilationError, match="unknown node kind"):
        scheduler.run(
            graph,
            run_id="kernel-rejection",
            internal_only=True,
        )

    assert dispatched == []


def test_failed_fanin_blocks_dispatch_and_isolation_contention_is_visible(
    tmp_path: Path,
) -> None:
    dispatched: list[str] = []

    def fail_prepare(node: dict[str, object]) -> NodeExecutionResult:
        dispatched.append(str(node["id"]))
        return NodeExecutionResult(verdict="fail", output={"failed": node["id"]})

    scheduler = GraphScheduler(
        fail_prepare,
        receipts=ExecutionReceiptJournal(tmp_path / "failed-receipts"),
        pools=ResourcePoolRegistry(),
    )
    failed = scheduler.run(
        valid_graph(),
        run_id="fanin-failure",
        internal_only=True,
    )

    assert failed.verdict == "fail"
    assert dispatched == ["prepare"]
    assert failed.nodes[1].dispatched is False
    assert failed.nodes[1].fanin.failed == ("prepare",)

    contended_graph = deepcopy(valid_graph())
    contended_graph["spec"]["edges"] = []
    for node in contended_graph["spec"]["nodes"]:
        node["isolation"] = {"mode": "process", "writeScope": "scoped"}

    contention_scheduler = GraphScheduler(
        lambda node: NodeExecutionResult(verdict="pass", output=node["id"]),
        receipts=ExecutionReceiptJournal(tmp_path / "contention-receipts"),
        pools=ResourcePoolRegistry(),
    )
    contended = contention_scheduler.run(
        contended_graph,
        run_id="contention-visible",
        internal_only=True,
        write_paths={
            "prepare": {"shared/output.json"},
            "verify": {"shared/output.json"},
        },
    )

    assert contended.verdict == "pass"
    assert len(contended.contention_findings) == 1
    assert contended.contention_findings[0].path == "shared/output.json"
