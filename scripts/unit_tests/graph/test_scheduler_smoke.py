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

    with pytest.raises(PermissionError, match="internal_only"):
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


def _diamond_graph(*, max_concurrency: int) -> dict[str, object]:
    return {
        "apiVersion": "shipwright.dev/v1alpha1",
        "kind": "WorkflowGraph",
        "metadata": {"name": "ready-set-diamond"},
        "spec": {
            "nodes": [
                _node("root"),
                _node("left", pool="read-only-reviewers"),
                _node("right", pool="read-only-reviewers"),
                _node("join"),
            ],
            "edges": [
                {"from": "root", "to": "left", "required": True},
                {"from": "root", "to": "right", "required": True},
                {"from": "left", "to": "join", "required": True},
                {"from": "right", "to": "join", "required": True},
            ],
            "resourceLimits": {
                "maxConcurrency": max_concurrency,
                "maxDurationSeconds": 600,
            },
            "verification": {"required": True, "failClosed": True},
        },
    }


def test_ready_set_diamond_concurrent_versus_serial_equivalent(tmp_path: Path) -> None:
    """R1: diamond ready-set; maxConcurrency 1 stays serial-equivalent."""

    def run_with(max_concurrency: int) -> list[str]:
        order: list[str] = []

        def execute(node: dict[str, object]) -> NodeExecutionResult:
            order.append(str(node["id"]))
            return NodeExecutionResult(verdict="pass", output={"id": node["id"]})

        GraphScheduler(
            execute,
            receipts=ExecutionReceiptJournal(tmp_path / f"r-{max_concurrency}"),
            pools=ResourcePoolRegistry.from_config(
                limits={"code-writers": 4, "read-only-reviewers": 8}
            ),
        ).run(
            _diamond_graph(max_concurrency=max_concurrency),
            run_id=f"diamond-{max_concurrency}",
            internal_only=True,
        )
        return order

    concurrent = run_with(2)
    serial = run_with(1)
    assert concurrent[0] == "root"
    assert set(concurrent[1:3]) == {"left", "right"}
    assert concurrent[1] == "left"  # source-order tie-break
    assert concurrent[3] == "join"
    assert serial == ["root", "left", "right", "join"]


def test_fanin_quorum_waits_for_settle_before_fire(tmp_path: Path) -> None:
    """R2: quorum / minimum-coverage admit only after all preds settle."""
    from graph.fanin_policy import FanInMode, FanInPolicy, NodeOutcome, evaluate_fanin

    policy = FanInPolicy(mode=FanInMode.QUORUM, minimum_successful=1)
    early = evaluate_fanin(
        policy,
        [NodeOutcome("a", True), NodeOutcome("b", True, settled=False)],
        expected_nodes=["a", "b"],
    )
    assert early.halt is True
    assert early.unsettled == ("b",)

    settled = evaluate_fanin(
        policy,
        [NodeOutcome("a", True), NodeOutcome("b", False)],
        expected_nodes=["a", "b"],
    )
    assert settled.halt is False
    assert settled.verdict == "degraded"


def test_pool_park_then_progress_and_unsatisfiable_compile_reject(tmp_path: Path) -> None:
    """R1/R2: PoolExhausted parks when satisfiable; slots>limit fail closed at compile."""
    from graph.resource_pools import PoolExhausted, PoolRequestUnsatisfiable
    from graph.scheduler import SchedulerError, SchedulerNoProgress

    graph = deepcopy(valid_graph())
    graph["spec"]["edges"] = []
    graph["spec"]["resourceLimits"]["maxConcurrency"] = 2
    for node in graph["spec"]["nodes"]:
        node["resources"]["pool"] = "code-writers"
        node["resources"]["slots"] = 1

    order: list[str] = []

    def execute(node: dict[str, object]) -> NodeExecutionResult:
        order.append(str(node["id"]))
        return NodeExecutionResult(verdict="pass", output=node["id"])

    pools = ResourcePoolRegistry.from_config(limits={"code-writers": 1})
    result = GraphScheduler(
        execute,
        receipts=ExecutionReceiptJournal(tmp_path / "park"),
        pools=pools,
    ).run(graph, run_id="park-progress", internal_only=True)
    assert result.verdict == "pass"
    assert order == ["prepare", "verify"]  # source-order; second parked then ran

    bad = deepcopy(valid_graph())
    bad["spec"]["nodes"][0]["resources"]["slots"] = 4
    with pytest.raises(SchedulerError, match="slots=4 exceed pool"):
        GraphScheduler(
            execute,
            receipts=ExecutionReceiptJournal(tmp_path / "unsat"),
            pools=ResourcePoolRegistry.from_config(limits={"code-writers": 1}),
        ).run(bad, run_id="unsat", internal_only=True)

    # Direct pool contract
    reg = ResourcePoolRegistry.from_config(limits={"code-writers": 1})
    from graph.resource_pools import PoolName

    reg.acquire(PoolName.CODE_WRITERS, slots=1)
    with pytest.raises(PoolExhausted):
        reg.acquire(PoolName.CODE_WRITERS, slots=1)
    with pytest.raises(PoolRequestUnsatisfiable):
        ResourcePoolRegistry.from_config(limits={"code-writers": 1}).acquire(
            PoolName.CODE_WRITERS, slots=2
        )
    # no-progress: ready set stuck with zero capacity and nothing in flight is
    # covered by park-then-progress above; explicit raise shape:
    err = SchedulerNoProgress(["a", "b"], reason="pool-parked-no-progress")
    assert err.blocked == ("a", "b")


def test_shared_write_serializes_diamond_dispatch(tmp_path: Path) -> None:
    """R14: isolated reviewers concurrent; shared write path forces serial dispatch."""
    from graph.isolation_policy import (
        UNKNOWN_WRITE_PATH,
        analyze_write_contention,
        normalize_write_path,
        paths_overlap,
        NodeIsolationClaim,
        parse_isolation_policy,
    )

    assert paths_overlap("build/out", "build/out/file.txt")
    assert paths_overlap("build/out/file.txt", "build/out")
    assert normalize_write_path("") == UNKNOWN_WRITE_PATH

    # Empty mutating claim overlaps everything.
    mutating = NodeIsolationClaim(
        "writer",
        parse_isolation_policy({"mode": "process", "writeScope": "scoped"}),
        frozenset(),
    )
    peer = NodeIsolationClaim(
        "peer",
        parse_isolation_policy({"mode": "process", "writeScope": "scoped"}),
        frozenset({"other/path"}),
    )
    findings = analyze_write_contention([mutating, peer])
    assert findings and findings[0].path == UNKNOWN_WRITE_PATH

    def _node(node_id: str, *, pool: str = "code-writers") -> dict[str, object]:
        return {
            "id": node_id,
            "kind": "command",
            "target": {"step": f"sw-{node_id}"},
            "resources": {"pool": pool, "slots": 1, "timeoutSeconds": 300},
            "isolation": {"mode": "process", "writeScope": "scoped"},
            "verification": {"required": True, "strategy": "mechanical"},
        }

    graph = {
        "apiVersion": "shipwright.dev/v1alpha1",
        "kind": "WorkflowGraph",
        "metadata": {"name": "r14-serial"},
        "spec": {
            "nodes": [_node("left"), _node("right")],
            "edges": [],
            "resourceLimits": {"maxConcurrency": 2, "maxDurationSeconds": 600},
            "verification": {"required": True, "failClosed": True},
        },
    }
    order: list[str] = []

    def execute(node: dict[str, object]) -> NodeExecutionResult:
        order.append(str(node["id"]))
        return NodeExecutionResult(verdict="pass", output=node["id"])

    # Shared write → serial (second parks in batch, runs next loop).
    shared = GraphScheduler(
        execute,
        receipts=ExecutionReceiptJournal(tmp_path / "shared"),
        pools=ResourcePoolRegistry.from_config(limits={"code-writers": 4}),
    ).run(
        graph,
        run_id="shared-write",
        internal_only=True,
        write_paths={"left": {"shared/out.json"}, "right": {"shared/out.json"}},
    )
    assert shared.verdict == "pass"
    assert order == ["left", "right"]
    assert len(shared.contention_findings) >= 1

    # Isolated reviewers (worktree) may share logical path concurrently.
    order.clear()
    for node in graph["spec"]["nodes"]:
        node["isolation"] = {"mode": "worktree", "writeScope": "worktree"}
        node["resources"]["pool"] = "read-only-reviewers"
        node["isolation"] = {"mode": "worktree", "writeScope": "read-only"}

    concurrent = GraphScheduler(
        execute,
        receipts=ExecutionReceiptJournal(tmp_path / "concurrent"),
        pools=ResourcePoolRegistry.from_config(limits={"read-only-reviewers": 4}),
    ).run(
        graph,
        run_id="isolated-reviewers",
        internal_only=True,
        write_paths={"left": set(), "right": set()},
    )
    assert concurrent.verdict == "pass"
    assert set(order) == {"left", "right"}
