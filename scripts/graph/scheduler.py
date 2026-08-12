#!/usr/bin/env python3
"""Internal-only runtime scheduler for validated WorkflowGraph documents."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence, Set
from dataclasses import dataclass, field
from typing import Any

from graph.execution_receipts import ExecutionReceiptJournal
from graph.fanin_policy import (
    FanInMode,
    FanInPolicy,
    FanInResult,
    NodeOutcome,
    evaluate_fanin,
    parse_fanin_policy,
)
from graph.ir import WorkflowGraphValidationError
from graph.isolation_policy import (
    ContentionFinding,
    NodeIsolationClaim,
    analyze_write_contention,
    parse_isolation_policy,
)
from graph.kernel_compiler import compile_workflow_graph
from graph.resource_pools import PoolName, ResourcePoolRegistry


class SchedulerError(RuntimeError):
    """Base class for graph scheduling failures."""


class InternalSchedulerDisabled(SchedulerError):
    """Raised when the pre-cutover scheduler is invoked without its internal gate."""


@dataclass(frozen=True)
class NodeExecutionResult:
    """Normalized result returned by a node executor."""

    verdict: str
    output: Any = None
    model: str = "unknown"
    attempts: int = 1
    tokens: int = 0
    duration_ms: int = 0
    coverage: Mapping[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.verdict == "pass"


@dataclass(frozen=True)
class NodeRun:
    """One node's observable scheduling outcome."""

    node_id: str
    verdict: str
    dispatched: bool
    fanin: FanInResult
    output_hash: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class SchedulerRun:
    """Complete deterministic result for one graph run."""

    run_id: str
    graph_hash: str
    verdict: str
    nodes: tuple[NodeRun, ...]
    receipts: tuple[dict[str, Any], ...]
    contention_findings: tuple[ContentionFinding, ...]
    pool_snapshot: Mapping[str, Any]


NodeExecutor = Callable[[dict[str, Any]], NodeExecutionResult]


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _topological_order(graph: Mapping[str, Any]) -> tuple[str, ...]:
    nodes = graph["spec"]["nodes"]
    source_order = {node["id"]: index for index, node in enumerate(nodes)}
    incoming = {node["id"]: 0 for node in nodes}
    outgoing: dict[str, list[str]] = {node["id"]: [] for node in nodes}
    for edge in graph["spec"]["edges"]:
        incoming[edge["to"]] += 1
        outgoing[edge["from"]].append(edge["to"])

    ready = sorted(
        (node_id for node_id, count in incoming.items() if count == 0),
        key=source_order.__getitem__,
    )
    ordered: list[str] = []
    while ready:
        node_id = ready.pop(0)
        ordered.append(node_id)
        for successor in outgoing[node_id]:
            incoming[successor] -= 1
            if incoming[successor] == 0:
                ready.append(successor)
                ready.sort(key=source_order.__getitem__)
    if len(ordered) != len(nodes):
        raise WorkflowGraphValidationError("workflow graph contains a cycle")
    return tuple(ordered)


def _predecessors(graph: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    result: dict[str, list[str]] = {
        node["id"]: [] for node in graph["spec"]["nodes"]
    }
    for edge in graph["spec"]["edges"]:
        result[edge["to"]].append(edge["from"])
    return {node_id: tuple(items) for node_id, items in result.items()}


def _default_fanin(predecessors: Sequence[str]) -> FanInPolicy:
    return FanInPolicy(
        mode=FanInMode.ALL_SUCCESS,
        required_nodes=frozenset(predecessors),
    )


class GraphScheduler:
    """Execute validated graphs sequentially behind an explicit internal-only gate."""

    def __init__(
        self,
        executor: NodeExecutor,
        *,
        receipts: ExecutionReceiptJournal,
        pools: ResourcePoolRegistry,
    ) -> None:
        self._executor = executor
        self._receipts = receipts
        self._pools = pools

    def run(
        self,
        document: Mapping[str, Any],
        *,
        run_id: str,
        internal_only: bool = False,
        fanin_policies: Mapping[str, Mapping[str, Any] | FanInPolicy] | None = None,
        write_paths: Mapping[str, Set[str] | frozenset[str]] | None = None,
        kernel_options: Mapping[str, Any] | None = None,
    ) -> SchedulerRun:
        """Run a graph after all pre-dispatch checks have completed."""
        if not internal_only:
            raise InternalSchedulerDisabled(
                "graph scheduler is internal-only until runtime cutover"
            )

        compiled = compile_workflow_graph(document, **dict(kernel_options or {}))
        graph = compiled["graph"]
        order = _topological_order(graph)
        graph_hash = str(compiled["graphHash"])
        by_id = {node["id"]: node for node in graph["spec"]["nodes"]}
        predecessors = _predecessors(graph)
        policies = fanin_policies or {}

        claims = [
            NodeIsolationClaim(
                node_id=node_id,
                policy=parse_isolation_policy(by_id[node_id]["isolation"]),
                write_paths=frozenset((write_paths or {}).get(node_id, set())),
            )
            for node_id in order
        ]
        contention = tuple(analyze_write_contention(claims))

        outcomes: dict[str, NodeOutcome] = {}
        output_hashes: dict[str, str] = {}
        node_runs: list[NodeRun] = []
        persisted_receipts: list[dict[str, Any]] = []

        for node_id in order:
            expected = predecessors[node_id]
            raw_policy = policies.get(node_id)
            if isinstance(raw_policy, FanInPolicy):
                policy = raw_policy
            elif raw_policy is not None:
                policy = parse_fanin_policy(dict(raw_policy))
            else:
                policy = _default_fanin(expected)
            fanin = evaluate_fanin(
                policy,
                (outcomes[item] for item in expected if item in outcomes),
                expected_nodes=expected,
            )
            if fanin.halt:
                outcomes[node_id] = NodeOutcome(node_id, success=False)
                node_runs.append(
                    NodeRun(
                        node_id=node_id,
                        verdict="blocked",
                        dispatched=False,
                        fanin=fanin,
                        reason=fanin.reason,
                    )
                )
                continue

            node = by_id[node_id]
            idempotency_key = f"{run_id}:{graph_hash}:{node_id}"
            try:
                existing_receipt = self._receipts.get(node_id, idempotency_key)
            except KeyError:
                existing_receipt = None
            if existing_receipt is not None:
                stored_hashes = existing_receipt.get("outputHashes") or []
                output_hash = str(stored_hashes[0]) if stored_hashes else None
                if output_hash is not None:
                    output_hashes[node_id] = output_hash
                succeeded = existing_receipt.get("verdict") == "pass"
                outcomes[node_id] = NodeOutcome(node_id, success=succeeded)
                persisted_receipts.append(existing_receipt)
                node_runs.append(
                    NodeRun(
                        node_id=node_id,
                        verdict=str(existing_receipt.get("verdict") or "fail"),
                        dispatched=False,
                        fanin=fanin,
                        output_hash=output_hash,
                        reason="replayed complete receipt",
                    )
                )
                continue

            pool = PoolName(node["resources"]["pool"])
            slots = int(node["resources"]["slots"])
            self._pools.acquire(pool, slots=slots)
            try:
                result = self._executor(dict(node))
            finally:
                self._pools.release(pool, slots=slots)
            if not isinstance(result, NodeExecutionResult):
                raise SchedulerError(
                    f"executor returned invalid result for node {node_id}"
                )

            output_hash = _digest(result.output)
            payload = {
                "model": result.model,
                "attempts": result.attempts,
                "tokens": result.tokens,
                "durationMs": result.duration_ms,
                "inputHashes": [
                    output_hashes[item]
                    for item in expected
                    if item in output_hashes
                ],
                "outputHashes": [output_hash],
                "verdict": result.verdict,
                "coverage": dict(result.coverage),
            }
            receipt = self._receipts.record(
                node_id,
                idempotency_key,
                payload,
            )
            persisted_receipts.append(receipt)
            output_hashes[node_id] = output_hash
            outcomes[node_id] = NodeOutcome(node_id, success=result.success)
            node_runs.append(
                NodeRun(
                    node_id=node_id,
                    verdict=result.verdict,
                    dispatched=True,
                    fanin=fanin,
                    output_hash=output_hash,
                )
            )

        verdict = (
            "pass"
            if all(item.verdict == "pass" for item in node_runs)
            else "fail"
        )
        return SchedulerRun(
            run_id=run_id,
            graph_hash=graph_hash,
            verdict=verdict,
            nodes=tuple(node_runs),
            receipts=tuple(persisted_receipts),
            contention_findings=contention,
            pool_snapshot=self._pools.snapshot(),
        )
