#!/usr/bin/env python3
"""Property tests: cancelled node never accepted-success (PRD 323 R2)."""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.execution_backend import (  # noqa: E402
    ExecutionBackend,
    ExecutionHandle,
    PollPhase,
    PollStatus,
    SubmitRequest,
    SubmitResult,
    TerminalEnvelope,
)
from graph.execution_receipts import ExecutionReceiptJournal  # noqa: E402
from graph.resource_pools import ResourcePoolRegistry  # noqa: E402
from graph.scheduler import (  # noqa: E402
    CancelMode,
    GraphScheduler,
    NodeExecutionResult,
    SchedulerError,
)


def _node(node_id: str) -> dict[str, object]:
    return {
        "id": node_id,
        "kind": "command",
        "target": {"step": f"sw-{node_id}"},
        "resources": {"pool": "code-writers", "slots": 1, "timeoutSeconds": 30},
        "isolation": {"mode": "worktree", "writeScope": "worktree"},
        "verification": {"required": True, "strategy": "mechanical"},
        "execution": {"purity": "mutating"},
    }


def _graph(nodes: list[dict[str, object]]) -> dict[str, object]:
    return {
        "apiVersion": "shipwright.dev/v1alpha1",
        "kind": "WorkflowGraph",
        "metadata": {"name": "cancel-prop"},
        "spec": {
            "nodes": nodes,
            "edges": [],
            "resourceLimits": {"maxConcurrency": 1, "maxDurationSeconds": 60},
            "verification": {"required": True, "failClosed": True},
        },
    }


class _FencingBackend(ExecutionBackend):
    def __init__(self, *, delay_s: float = 0.08) -> None:
        self._delay = delay_s
        self._records: dict[str, dict[str, object]] = {}
        self.late_writes: list[str] = []

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
            from graph.execution_backend import AdvisoryExecutionReport

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
        from graph.execution_backend import AdvisoryExecutionReport

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
        return PollStatus(phase=PollPhase.CANCEL_ACKNOWLEDGED, cancel_acknowledged=True)

    def result(self, handle: ExecutionHandle) -> TerminalEnvelope:
        record = self._records[handle.handle_id]
        terminal = record.get("terminal")
        if terminal is None:
            self.late_writes.append(handle.handle_id)
            raise SchedulerError("late write refused after cancel ack")
        return terminal  # type: ignore[return-value]


@pytest.mark.parametrize("node_id", ["mutate", "writer", "n-9"])
def test_cancelled_node_never_accepted_success(tmp_path: Path, node_id: str) -> None:
    backend = _FencingBackend()
    scheduler_box: list[GraphScheduler] = []

    def execute(node: dict[str, object]) -> NodeExecutionResult:
        return NodeExecutionResult(verdict="pass", output=str(node["id"]))

    scheduler = GraphScheduler(
        execute,
        receipts=ExecutionReceiptJournal(tmp_path / f"r-{node_id}"),
        pools=ResourcePoolRegistry(),
        backend=backend,
    )
    scheduler_box.append(scheduler)

    def _cancel() -> None:
        time.sleep(0.02)
        scheduler_box[0].request_cancel(CancelMode.CANCEL_AND_DRAIN)

    threading.Thread(target=_cancel, daemon=True).start()
    result = scheduler.run(_graph([_node(node_id)]), run_id=f"cancel-{node_id}", internal_only=True)
    assert result.verdict == "fail"
    assert result.nodes[0].verdict == "cancelled"
    assert result.nodes[0].verdict != "pass"
    assert "accepted-success" not in str(result)
    assert backend.late_writes == []
