#!/usr/bin/env python3
"""Read-only, receipts-backed observability for completed graph runs."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from graph.cost_telemetry import observability_fields
from graph.execution_receipts import ExecutionReceiptJournal

READ_ONLY_COMMANDS = frozenset({"status", "show", "explain", "critical-path"})
MUTATING_COMMANDS = frozenset({"retry", "replay"})


class ObservabilityError(ValueError):
    """Raised when graph evidence or an observability request is invalid."""


@dataclass(frozen=True)
class CriticalPathNode:
    node_id: str
    cumulative_duration_ms: int


def _receipt_index(
    receipts: Iterable[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for receipt in receipts:
        node_id = receipt.get("nodeId")
        if not isinstance(node_id, str) or not node_id:
            raise ObservabilityError("receipt is missing nodeId")
        if node_id in indexed:
            raise ObservabilityError(f"multiple completed receipts for node {node_id}")
        indexed[node_id] = dict(receipt)
    return indexed


class GraphObservability:
    """Query immutable graph and receipt snapshots without dispatching work."""

    def __init__(
        self,
        graph: Mapping[str, Any],
        receipts: Iterable[Mapping[str, Any]],
        *,
        run_id: str = "",
    ) -> None:
        self._graph = graph
        self._run_id = run_id
        self._receipts = _receipt_index(receipts)
        try:
            nodes = graph["spec"]["nodes"]
            edges = graph["spec"]["edges"]
        except (KeyError, TypeError) as exc:
            raise ObservabilityError("invalid WorkflowGraph evidence") from exc
        self._node_ids = tuple(str(node["id"]) for node in nodes)
        self._edges = tuple((str(edge["from"]), str(edge["to"])) for edge in edges)

    @classmethod
    def from_receipt_journal(
        cls,
        graph: Mapping[str, Any],
        journal: ExecutionReceiptJournal,
        *,
        run_id: str,
    ) -> GraphObservability:
        """Build a run-scoped view from the durable receipt journal."""
        return cls(graph, journal.list_run_receipts(run_id), run_id=run_id)

    def status(self) -> dict[str, Any]:
        completed = sum(
            receipt.get("state", "complete") == "complete"
            for receipt in self._receipts.values()
        )
        failed = sorted(
            node_id
            for node_id, receipt in self._receipts.items()
            if receipt.get("verdict") != "pass"
        )
        missing = sorted(set(self._node_ids) - set(self._receipts))
        if failed:
            verdict = "fail"
        elif missing:
            verdict = "partial"
        else:
            verdict = "pass"
        return {
            "runId": self._run_id,
            "verdict": verdict,
            "nodeCount": len(self._node_ids),
            "completedCount": completed,
            "failedNodes": failed,
            "missingNodes": missing,
        }

    def show(self, node_id: str) -> dict[str, Any]:
        try:
            receipt = self._receipts[node_id]
        except KeyError:
            raise ObservabilityError(f"no completed receipt for node {node_id}") from None
        return {
            "nodeId": node_id,
            "receipt": dict(receipt),
            "telemetry": observability_fields(receipt),
        }

    def explain(self, node_id: str) -> dict[str, Any]:
        shown = self.show(node_id)
        predecessors = sorted(source for source, target in self._edges if target == node_id)
        receipt = shown["receipt"]
        return {
            "nodeId": node_id,
            "verdict": receipt.get("verdict"),
            "predecessors": predecessors,
            "inputHashes": list(receipt.get("inputHashes") or []),
            "outputHashes": list(receipt.get("outputHashes") or []),
            "coverage": dict(receipt.get("coverage") or {}),
            "model": receipt.get("model", "unknown"),
            "attempts": receipt.get("attempts", 0),
        }

    def critical_path(self) -> dict[str, Any]:
        incoming = {node_id: 0 for node_id in self._node_ids}
        outgoing = {node_id: [] for node_id in self._node_ids}
        for source, target in self._edges:
            if source not in incoming or target not in incoming:
                raise ObservabilityError("edge references unknown node")
            incoming[target] += 1
            outgoing[source].append(target)
        ready = [node_id for node_id in self._node_ids if incoming[node_id] == 0]
        order: list[str] = []
        while ready:
            node_id = ready.pop(0)
            order.append(node_id)
            for successor in outgoing[node_id]:
                incoming[successor] -= 1
                if incoming[successor] == 0:
                    ready.append(successor)
        if len(order) != len(self._node_ids):
            raise ObservabilityError("critical path is undefined for a cyclic graph")

        distances: dict[str, int] = {}
        previous: dict[str, str | None] = {}
        for node_id in order:
            duration = int(self._receipts.get(node_id, {}).get("durationMs", 0))
            predecessors = [source for source, target in self._edges if target == node_id]
            parent = max(predecessors, key=lambda item: distances[item], default=None)
            distances[node_id] = duration + (distances[parent] if parent else 0)
            previous[node_id] = parent
        end = max(order, key=distances.__getitem__, default=None)
        path = []
        while end is not None:
            path.append(end)
            end = previous[end]
        path.reverse()
        return {
            "runId": self._run_id,
            "durationMs": distances[path[-1]] if path else 0,
            "nodes": [
                {
                    "nodeId": node_id,
                    "cumulativeDurationMs": distances[node_id],
                }
                for node_id in path
            ],
        }

    def command(self, name: str, *, node_id: str | None = None) -> dict[str, Any]:
        """Dispatch only the initial read-only command surface."""
        if name in MUTATING_COMMANDS:
            raise ObservabilityError(
                f"{name} is gated until crash-resume and replay support lands"
            )
        if name not in READ_ONLY_COMMANDS:
            raise ObservabilityError(f"unknown graph observability command: {name}")
        if name == "status":
            return self.status()
        if name == "critical-path":
            return self.critical_path()
        if not node_id:
            raise ObservabilityError(f"{name} requires node_id")
        return self.show(node_id) if name == "show" else self.explain(node_id)
