#!/usr/bin/env python3
"""R13/R16 cancel, compensation, and durable in-flight journal fixtures."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.crash_replay_harness import CrashReplayHarness  # noqa: E402
from graph.execution_receipts import (  # noqa: E402
    ExecutionReceiptJournal,
    ReceiptStoreFull,
    default_store_root,
)
from graph.resource_pools import ResourcePoolRegistry  # noqa: E402
from graph.scheduler import (  # noqa: E402
    CancelMode,
    GraphScheduler,
    NodeExecutionResult,
)


def _node(
    node_id: str,
    *,
    pool: str = "code-writers",
    timeout: int = 300,
    write_scope: str = "worktree",
) -> dict[str, object]:
    return {
        "id": node_id,
        "kind": "command",
        "target": {"step": f"sw-{node_id}"},
        "resources": {"pool": pool, "slots": 1, "timeoutSeconds": timeout},
        "isolation": {"mode": "worktree", "writeScope": write_scope},
        "verification": {"required": True, "strategy": "mechanical"},
    }


def _graph(
    nodes: list[dict[str, object]],
    edges: list[dict[str, object]],
    *,
    max_concurrency: int = 2,
    max_duration: int = 600,
) -> dict[str, object]:
    return {
        "apiVersion": "shipwright.dev/v1alpha1",
        "kind": "WorkflowGraph",
        "metadata": {"name": "cancel-journal"},
        "spec": {
            "nodes": nodes,
            "edges": edges,
            "resourceLimits": {
                "maxConcurrency": max_concurrency,
                "maxDurationSeconds": max_duration,
            },
            "verification": {"required": True, "failClosed": True},
        },
    }


def _receipt(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "model": "build-model",
        "attempts": 1,
        "tokens": 1,
        "durationMs": 1,
        "inputHashes": [],
        "outputHashes": ["a" * 64],
        "verdict": "pass",
        "coverage": {},
    }
    payload.update(overrides)
    return payload


def test_r13_run_scoped_store_gc_ceiling_and_corrupt_quarantine(tmp_path: Path) -> None:
    """R13: per-run index, retention/GC, size ceiling, corrupt quarantine."""
    store = default_store_root(tmp_path)
    assert store == tmp_path / ".cursor" / "sw-graph-runs"

    journal = ExecutionReceiptJournal.for_run(store, "run-a", size_ceiling_bytes=10_000)
    journal.begin(
        "build",
        "run-a:hash:build",
        _receipt(verdict="running", coverage={"intent": True, "mutating": True}),
    )
    journal.finish("build", "run-a:hash:build", _receipt())
    journal.write_pool_snapshot(
        {"code-writers": {"limit": 1, "inUse": 0, "available": 1, "waiters": 0}},
        parked=["parked-node"],
        queue=["queued-node"],
    )
    journal.write_telemetry({"tokens": 3})

    assert journal.list_run_receipts("run-a")
    assert journal.read_pool_snapshot()["parked"] == ["parked-node"]
    assert journal.read_telemetry()["tokens"] == 3
    assert journal.list_inflight_intents() == []

    # Corrupt one complete receipt; unrelated list queries still succeed.
    other = ExecutionReceiptJournal.for_run(store, "run-b")
    other.finish("verify", "run-b:hash:verify", _receipt())
    victim = journal.complete_path("build", "run-a:hash:build")
    victim.write_text("{", encoding="utf-8")
    assert journal.list_receipts() == []
    assert list(journal.quarantine_root.iterdir())
    assert len(other.list_receipts()) == 1

    # Size ceiling refuses oversized writes.
    tiny = ExecutionReceiptJournal.for_run(store, "run-c", size_ceiling_bytes=32)
    with pytest.raises(ReceiptStoreFull):
        tiny.finish("x", "run-c:hash:x", _receipt(coverage={"pad": "z" * 200}))

    # GC deletes aged completes.
    aged = ExecutionReceiptJournal.for_run(store, "run-d")
    aged.finish("old", "run-d:hash:old", _receipt())
    path = aged.complete_path("old", "run-d:hash:old")
    import os

    os.utime(path, (1, 1))
    report = aged.gc(max_age_seconds=10, now=10_000)
    assert report["deleted"] >= 1
    assert aged.list_receipts() == []


def test_r16_cancel_and_drain_releases_slots_and_terminals(tmp_path: Path) -> None:
    """R16: cancel-and-drain terminals every node and releases pool slots/leases."""
    graph = _graph(
        [_node("a"), _node("b"), _node("c")],
        [
            {"from": "a", "to": "b", "required": True},
            {"from": "a", "to": "c", "required": True},
        ],
        max_concurrency=2,
    )
    journal = ExecutionReceiptJournal.for_run(tmp_path / "store", "cancel-run")
    pools = ResourcePoolRegistry.from_config(limits={"code-writers": 4})
    released: list[str] = []
    compensated: list[str] = []

    def execute(node: dict[str, object]) -> NodeExecutionResult:
        node_id = str(node["id"])
        if node_id == "a":
            scheduler.request_cancel(CancelMode.CANCEL_AND_DRAIN)
        return NodeExecutionResult(
            verdict="pass", output={"node": node_id}, model="fix", duration_ms=1
        )

    scheduler = GraphScheduler(
        execute,
        receipts=journal,
        pools=pools,
        lease_releaser=released.append,
        compensation=compensated.append,
    )
    result = scheduler.run(graph, run_id="cancel-run", internal_only=True)

    assert result.verdict == "fail"
    assert result.cancel_mode == "cancel-and-drain"
    by_id = {node.node_id: node for node in result.nodes}
    assert by_id["a"].verdict == "pass"
    assert by_id["b"].verdict == "cancelled"
    assert by_id["c"].verdict == "cancelled"
    assert set(released) >= {"a", "b", "c"}
    assert pools.snapshot()["code-writers"]["inUse"] == 0
    assert journal.read_pool_snapshot() is not None
    # begin() intents were written pre-dispatch then finished.
    assert all(r.get("state") == "complete" for r in journal.list_receipts())


def test_r16_let_settle_finishes_inflight_batch(tmp_path: Path) -> None:
    """R16: let-settle finishes admitted work; no new admissions."""
    graph = _graph(
        [_node("a"), _node("b"), _node("c")],
        [],
        max_concurrency=2,
    )
    journal = ExecutionReceiptJournal(tmp_path / "receipts")
    pools = ResourcePoolRegistry.from_config(limits={"code-writers": 4})
    order: list[str] = []

    def execute(node: dict[str, object]) -> NodeExecutionResult:
        node_id = str(node["id"])
        order.append(node_id)
        if node_id == "a":
            scheduler.request_cancel(CancelMode.LET_SETTLE)
        return NodeExecutionResult(
            verdict="pass", output={"node": node_id}, model="fix", duration_ms=1
        )

    scheduler = GraphScheduler(execute, receipts=journal, pools=pools)
    result = scheduler.run(graph, run_id="settle-run", internal_only=True)

    assert result.verdict == "fail"
    assert result.cancel_mode == "let-settle"
    # First batch admits a+b (source order); let-settle finishes b; c cancelled.
    assert "a" in order and "b" in order
    assert "c" not in order
    by_id = {node.node_id: node for node in result.nodes}
    assert by_id["a"].verdict == "pass"
    assert by_id["b"].verdict == "pass"
    assert by_id["c"].verdict == "cancelled"
    assert pools.snapshot()["code-writers"]["inUse"] == 0


def test_r16_timeout_seconds_and_max_duration(tmp_path: Path) -> None:
    """R16: honor timeoutSeconds and maxDurationSeconds."""
    graph = _graph(
        [_node("slow", timeout=1)],
        [],
        max_concurrency=1,
        max_duration=600,
    )
    journal = ExecutionReceiptJournal(tmp_path / "receipts")
    pools = ResourcePoolRegistry()

    def execute(_node: dict[str, object]) -> NodeExecutionResult:
        return NodeExecutionResult(
            verdict="pass",
            output={"node": "slow"},
            model="fix",
            duration_ms=5000,  # > timeoutSeconds * 1000
        )

    result = GraphScheduler(execute, receipts=journal, pools=pools).run(
        graph, run_id="timeout-run", internal_only=True
    )
    assert result.verdict == "fail"
    assert result.nodes[0].verdict == "fail"
    assert "timeoutSeconds" in result.nodes[0].reason

    # maxDurationSeconds via injected clock.
    clock = {"t": 0.0}

    def tick() -> float:
        return clock["t"]

    def execute_then_advance(node: dict[str, object]) -> NodeExecutionResult:
        clock["t"] += 10
        return NodeExecutionResult(
            verdict="pass", output={"node": node["id"]}, model="fix", duration_ms=1
        )

    long_graph = _graph(
        [_node("one"), _node("two")],
        [{"from": "one", "to": "two", "required": True}],
        max_duration=5,
    )
    result2 = GraphScheduler(
        execute_then_advance,
        receipts=ExecutionReceiptJournal(tmp_path / "receipts2"),
        pools=ResourcePoolRegistry(),
        clock=tick,
    ).run(long_graph, run_id="maxdur-run", internal_only=True)
    assert result2.verdict == "fail"
    assert any(node.verdict == "cancelled" for node in result2.nodes)


def test_r13_r16_teardown_and_cancel_drain_harness(tmp_path: Path) -> None:
    """R13/R16: teardown keeps journal readable; cancel-and-drain releases leases."""
    graph = _graph(
        [_node("prepare"), _node("verify", pool="read-only-reviewers", write_scope="read-only")],
        [{"from": "prepare", "to": "verify", "required": True}],
    )
    harness = CrashReplayHarness(graph, root=tmp_path / "harness")

    # Seed a completed run through the scheduler-backed cancel path first.
    drain = harness.cancel_and_drain(run_id="drain-1", cancel_after="prepare")
    assert drain.verdict == "fail"
    assert drain.cancelled_nodes
    assert "prepare" in drain.released_leases
    assert all(
        snap["inUse"] == 0 for snap in drain.pool_snapshot.values()
    )

    # Persist intents + telemetry, then teardown-read.
    journal = ExecutionReceiptJournal.for_run(
        default_store_root(tmp_path / "harness"), "durable-1"
    )
    journal.begin(
        "prepare",
        "durable-1:g:prepare",
        _receipt(verdict="running", coverage={"intent": True, "mutating": True}),
    )
    journal.finish("verify", "durable-1:g:verify", _receipt())
    journal.write_pool_snapshot({"code-writers": {"inUse": 0}})
    journal.write_telemetry({"tokens": 9})
    harness.receipts = journal

    report = harness.teardown_and_read("durable-1")
    assert report.readable is True
    assert report.telemetry is not None
    assert report.telemetry.get("tokens") == 9
    assert report.pool_snapshot is not None
    assert any(r.get("nodeId") == "verify" for r in report.receipts)
    # In-flight intent remains readable after teardown.
    assert any(i.get("nodeId") == "prepare" for i in report.intents) or any(
        r.get("nodeId") == "prepare" for r in report.receipts
    )


def test_begin_before_dispatch_for_mutating_nodes(tmp_path: Path) -> None:
    """R16: mutating nodes persist begin() intent before executor runs."""
    seen_intents: list[dict[str, object]] = []
    graph = _graph([_node("mutate")], [])
    journal = ExecutionReceiptJournal(tmp_path / "receipts")
    pools = ResourcePoolRegistry()

    def execute(node: dict[str, object]) -> NodeExecutionResult:
        seen_intents.extend(journal.list_inflight_intents())
        return NodeExecutionResult(
            verdict="pass", output={"node": node["id"]}, model="fix", duration_ms=1
        )

    GraphScheduler(execute, receipts=journal, pools=pools).run(
        graph, run_id="intent-run", internal_only=True
    )
    assert seen_intents
    assert seen_intents[0]["coverage"]["mutating"] is True
    assert seen_intents[0]["coverage"]["intent"] is True
    assert journal.list_inflight_intents() == []
    assert len(journal.list_receipts()) == 1
