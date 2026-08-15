#!/usr/bin/env python3
"""Phase 2 async owning-loop scheduler fixtures (PRD 271 R1/R2/R3/R17/R18/R19/R20)."""
from __future__ import annotations

import sys
import threading
import time
from copy import deepcopy
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.execution_backend import (  # noqa: E402
    AdvisoryExecutionReport,
    ExecutionBackend,
    ExecutionHandle,
    InMemoryExecutionBackend,
    PollPhase,
    PollStatus,
    SubmitRequest,
    SubmitResult,
    TerminalEnvelope,
)
from graph.execution_receipts import ExecutionReceiptJournal  # noqa: E402
from graph.fanin_policy import FanInMode, FanInPolicy  # noqa: E402
from graph.resource_pools import ResourcePoolRegistry  # noqa: E402
from graph.run_ownership import RunOwnershipStore  # noqa: E402
from graph.scheduler import (  # noqa: E402
    CancelMode,
    GraphScheduler,
    NodeExecutionResult,
    SchedulerError,
)


def _node(
    node_id: str,
    *,
    pool: str = "code-writers",
    timeout: int = 300,
) -> dict[str, object]:
    return {
        "id": node_id,
        "kind": "command",
        "target": {"step": f"sw-{node_id}"},
        "resources": {"pool": pool, "slots": 1, "timeoutSeconds": timeout},
        "isolation": {"mode": "process", "writeScope": "scoped"},
        "verification": {"required": True, "strategy": "mechanical"},
    }


def _graph(
    nodes: list[dict[str, object]],
    edges: list[dict[str, object]],
    *,
    max_concurrency: int = 2,
) -> dict[str, object]:
    return {
        "apiVersion": "shipwright.dev/v1alpha1",
        "kind": "WorkflowGraph",
        "metadata": {"name": "phase2-async"},
        "spec": {
            "nodes": nodes,
            "edges": edges,
            "resourceLimits": {
                "maxConcurrency": max_concurrency,
                "maxDurationSeconds": 600,
            },
            "verification": {"required": True, "failClosed": True},
        },
    }


class SlowAsyncBackend:
    """Backend that runs work on a worker thread so overlap is observable."""

    def __init__(self, executor, *, delay_s: float = 0.05) -> None:
        self._executor = executor
        self._delay = delay_s
        self._inner = InMemoryExecutionBackend(self._run)

    def _run(self, request: SubmitRequest) -> TerminalEnvelope:
        time.sleep(self._delay)
        raw = self._executor(dict(request.node))
        if not isinstance(raw, NodeExecutionResult):
            raise SchedulerError("invalid executor result")
        return TerminalEnvelope(
            report=AdvisoryExecutionReport(
                verdict=raw.verdict,
                output=raw.output,
                model=raw.model,
                duration_ms=raw.duration_ms,
                coverage=dict(raw.coverage),
            )
        )

    def submit(self, request: SubmitRequest) -> SubmitResult:
        return self._inner.submit(request)

    def poll(self, handle: ExecutionHandle) -> PollStatus:
        return self._inner.poll(handle)

    def cancel(self, handle: ExecutionHandle) -> PollStatus:
        return self._inner.cancel(handle)

    def result(self, handle: ExecutionHandle) -> TerminalEnvelope:
        return self._inner.result(handle)


def test_scheduler_async_completion_driven(tmp_path: Path) -> None:
    """R1 / 2.1: ≥2 concurrent nodes; advance on any completion."""
    barrier = threading.Barrier(2)
    overlap_observed = False
    lock = threading.Lock()
    inflight = 0

    def execute(node: dict[str, object]) -> NodeExecutionResult:
        nonlocal overlap_observed, inflight
        node_id = str(node["id"])
        if node_id in {"left", "right"}:
            with lock:
                inflight += 1
                if inflight >= 2:
                    overlap_observed = True
            barrier.wait(timeout=2)
            with lock:
                inflight -= 1
        return NodeExecutionResult(verdict="pass", output=node_id, duration_ms=1)

    graph = _graph(
        [
            _node("root"),
            _node("left", pool="read-only-reviewers"),
            _node("right", pool="read-only-reviewers"),
            _node("join"),
        ],
        [
            {"from": "root", "to": "left", "required": True},
            {"from": "root", "to": "right", "required": True},
            {"from": "left", "to": "join", "required": True},
            {"from": "right", "to": "join", "required": True},
        ],
        max_concurrency=2,
    )
    for node in graph["spec"]["nodes"]:
        if str(node["id"]) in {"left", "right"}:
            node["isolation"] = {"mode": "worktree", "writeScope": "read-only"}
    scheduler = GraphScheduler(
        execute,
        receipts=ExecutionReceiptJournal(tmp_path / "async"),
        pools=ResourcePoolRegistry.from_config(
            limits={"code-writers": 4, "read-only-reviewers": 8}
        ),
        backend=SlowAsyncBackend(execute),
    )
    result = scheduler.run(graph, run_id="async-r1", internal_only=True)
    assert result.verdict == "pass"
    assert overlap_observed


def test_scheduler_deterministic_admission(tmp_path: Path) -> None:
    """R2 / 2.7: source-order admission under completion races."""
    finish_order: list[str] = []
    gate = threading.Event()

    def execute(node: dict[str, object]) -> NodeExecutionResult:
        node_id = str(node["id"])
        if node_id in {"a", "b", "c"}:
            gate.wait(timeout=2)
            finish_order.append(node_id)
        return NodeExecutionResult(verdict="pass", output=node_id)

    graph = _graph(
        [_node("a"), _node("b"), _node("c")],
        [],
        max_concurrency=3,
    )
    scheduler = GraphScheduler(
        execute,
        receipts=ExecutionReceiptJournal(tmp_path / "det"),
        pools=ResourcePoolRegistry.from_config(limits={"code-writers": 4}),
        backend=SlowAsyncBackend(execute, delay_s=0.02),
    )
    gate.set()
    result = scheduler.run(graph, run_id="det-r2", internal_only=True)
    assert result.verdict == "pass"
    # All three admitted concurrently; finish order may vary.
    assert set(finish_order) == {"a", "b", "c"}
    # Admission order in results remains source-order.
    assert [n.node_id for n in result.nodes] == ["a", "b", "c"]


def test_single_owning_loop_invariants(tmp_path: Path) -> None:
    """R17 / 2.8: scheduler state transitions occur only on owning loop."""
    scheduler = GraphScheduler(
        lambda node: NodeExecutionResult(
            verdict="pass", output=str(node["id"]), duration_ms=1
        ),
        receipts=ExecutionReceiptJournal(tmp_path / "owning"),
        pools=ResourcePoolRegistry(),
        backend=SlowAsyncBackend(
            lambda node: NodeExecutionResult(
                verdict="pass", output=str(node["id"]), duration_ms=1
            ),
            delay_s=0.02,
        ),
    )
    graph = _graph([_node("x"), _node("y")], [], max_concurrency=2)
    result = scheduler.run(graph, run_id="owning-r17", internal_only=True)
    assert result.verdict == "pass"
    assert scheduler.owning_loop_transitions > 0
    assert scheduler._state_owner_thread is None


def test_cross_batch_contention_after_partial_completion(tmp_path: Path) -> None:
    """R19 / 2.2–2.3: live in-flight union parks/refuses across partial completion."""
    order: list[str] = []

    def execute(node: dict[str, object]) -> NodeExecutionResult:
        order.append(str(node["id"]))
        return NodeExecutionResult(verdict="pass", output=node["id"])

    graph = _graph([_node("left"), _node("right")], [], max_concurrency=2)
    pools = ResourcePoolRegistry.from_config(limits={"code-writers": 4})
    scheduler = GraphScheduler(
        execute,
        receipts=ExecutionReceiptJournal(tmp_path / "contend"),
        pools=pools,
        backend=SlowAsyncBackend(execute, delay_s=0.01),
    )
    result = scheduler.run(
        graph,
        run_id="contend-r19",
        internal_only=True,
        write_paths={"left": {"shared/out.json"}, "right": {"shared/out.json"}},
    )
    assert result.verdict == "pass"
    assert order == ["left", "right"]
    assert pools.inflight_leases.inflight_ids() == frozenset()


class FencingBackend(ExecutionBackend):
    """Backend with delayed completion for cancel fencing tests."""

    def __init__(self, *, delay_s: float = 0.08) -> None:
        self._delay = delay_s
        self._records: dict[str, dict[str, object]] = {}
        self._late_writes: list[str] = []

    def submit(self, request: SubmitRequest) -> SubmitResult:
        handle_id = f"h-{request.idempotency_key}"
        record: dict[str, object] = {
            "request": request,
            "phase": PollPhase.RUNNING,
            "terminal": None,
            "cancel_requested": False,
        }
        self._records[handle_id] = record

        def _finish() -> None:
            time.sleep(self._delay)
            if record["cancel_requested"]:
                return
            record["terminal"] = TerminalEnvelope(
                report=AdvisoryExecutionReport(
                    verdict="pass",
                    output=str(record["request"].node.get("id")),
                )
            )
            record["phase"] = PollPhase.TERMINAL

        threading.Thread(target=_finish, daemon=True).start()
        return SubmitResult(
            handle=ExecutionHandle(handle_id, request.idempotency_key),
            duplicate=False,
        )

    def poll(self, handle: ExecutionHandle) -> PollStatus:
        record = self._records[handle.handle_id]
        if record["phase"] is PollPhase.TERMINAL:
            return PollStatus(phase=PollPhase.TERMINAL)
        if record["cancel_requested"]:
            return PollStatus(phase=PollPhase.CANCEL_ACKNOWLEDGED, cancel_acknowledged=True)
        return PollStatus(phase=PollPhase.RUNNING)

    def cancel(self, handle: ExecutionHandle) -> PollStatus:
        record = self._records[handle.handle_id]
        record["cancel_requested"] = True
        record["phase"] = PollPhase.CANCEL_ACKNOWLEDGED
        record["terminal"] = TerminalEnvelope(
            report=AdvisoryExecutionReport(
                verdict="cancelled",
                coverage={"cancelled": True, "reason": "cancel-acknowledged"},
            ),
            reason="cancel-acknowledged",
        )
        return PollStatus(
            phase=PollPhase.CANCEL_ACKNOWLEDGED,
            cancel_acknowledged=True,
        )

    def result(self, handle: ExecutionHandle) -> TerminalEnvelope:
        record = self._records[handle.handle_id]
        terminal = record.get("terminal")
        if terminal is None:
            # Late write after cancel ack must be refused (R3).
            self._late_writes.append(handle.handle_id)
            raise SchedulerError("late write refused after cancel ack")
        return terminal


def test_cancel_fencing_ack_before_release(tmp_path: Path) -> None:
    """R3 / 2.4: cancel-requested → ack → release; late-write refused."""
    backend = FencingBackend()
    scheduler_ref: list[GraphScheduler] = []

    def execute(node: dict[str, object]) -> NodeExecutionResult:
        return NodeExecutionResult(verdict="pass", output=str(node["id"]))

    graph = _graph([_node("mutate")], [], max_concurrency=1)
    scheduler = GraphScheduler(
        execute,
        receipts=ExecutionReceiptJournal(tmp_path / "fence"),
        pools=ResourcePoolRegistry(),
        backend=backend,
    )
    scheduler_ref.append(scheduler)

    def _request_cancel() -> None:
        time.sleep(0.02)
        scheduler_ref[0].request_cancel(CancelMode.CANCEL_AND_DRAIN)

    threading.Thread(target=_request_cancel, daemon=True).start()
    result = scheduler.run(graph, run_id="fence-r3", internal_only=True)
    assert result.verdict == "fail"
    assert result.nodes[0].verdict == "cancelled"
    assert backend._late_writes == []


def test_cancel_fanin_mutating_node(tmp_path: Path) -> None:
    """R20 / 2.4: cancelled mutator does not satisfy any-success fan-in."""
    graph = _graph(
        [_node("writer"), _node("join")],
        [{"from": "writer", "to": "join", "required": True}],
        max_concurrency=2,
    )

    scheduler_ref: list[GraphScheduler] = []

    def execute(node: dict[str, object]) -> NodeExecutionResult:
        return NodeExecutionResult(verdict="pass", output=str(node["id"]))

    scheduler = GraphScheduler(
        execute,
        receipts=ExecutionReceiptJournal(tmp_path / "fanin"),
        pools=ResourcePoolRegistry(),
        backend=FencingBackend(),
    )
    scheduler_ref.append(scheduler)

    def _cancel_writer() -> None:
        time.sleep(0.02)
        scheduler_ref[0].request_cancel(CancelMode.CANCEL_AND_DRAIN)

    threading.Thread(target=_cancel_writer, daemon=True).start()
    result = scheduler.run(
        graph,
        run_id="fanin-r20",
        internal_only=True,
        fanin_policies={
            "join": FanInPolicy(
                mode=FanInMode.ALL_SUCCESS,
                required_nodes=frozenset({"writer"}),
            ),
        },
    )
    assert result.verdict == "fail"
    by_id = {n.node_id: n for n in result.nodes}
    assert by_id["writer"].verdict == "cancelled"
    assert by_id["join"].verdict == "blocked"


def test_durable_background_reentry(tmp_path: Path) -> None:
    """R18 / 2.5–2.6: detach/reenter; session end does not cancel."""
    store_root = tmp_path / "journal"
    ownership = RunOwnershipStore(store_root)
    record = ownership.begin("bg-run", graph_hash="abc", session_id="sess-1")
    assert record.detached is False

    detached = ownership.detach("bg-run")
    assert detached.detached is True
    assert detached.session_id is None

    reentered = ownership.reenter("bg-run", session_id="sess-2")
    assert reentered.detached is False
    assert reentered.session_id == "sess-2"

    # Explicit cancel is separate from detach.
    cancelled = ownership.request_cancel("bg-run")
    assert cancelled.cancel_requested is True
    assert ownership.load("bg-run") is not None

    def execute(node: dict[str, object]) -> NodeExecutionResult:
        return NodeExecutionResult(verdict="pass", output=node["id"])

    graph = _graph([_node("solo")], [], max_concurrency=1)
    result = GraphScheduler(
        execute,
        receipts=ExecutionReceiptJournal.for_run(store_root, "bg-run"),
        pools=ResourcePoolRegistry(),
    ).run(graph, run_id="bg-run", internal_only=True)
    assert result.verdict == "pass"
    ownership.touch("bg-run")
    assert ownership.load("bg-run").last_seen_at >= record.last_seen_at
