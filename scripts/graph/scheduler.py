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
from graph.observability import GraphObservability
from graph.resource_pools import (
    PoolExhausted,
    PoolName,
    PoolRequestUnsatisfiable,
    ResourcePoolRegistry,
)


class SchedulerError(RuntimeError):
    """Base class for graph scheduling failures."""


class InternalSchedulerDisabled(SchedulerError):
    """Raised when the pre-cutover scheduler is invoked without its internal gate."""


class SchedulerNoProgress(SchedulerError):
    """Ready set non-empty but nothing can dispatch and nothing is in flight."""

    def __init__(self, blocked: Sequence[str], *, reason: str = "no-progress") -> None:
        blocked_ids = tuple(blocked)
        super().__init__(f"{reason}: blocked={','.join(blocked_ids)}")
        self.blocked = blocked_ids
        self.reason = reason


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

    def observability(self, graph: Mapping[str, Any]) -> GraphObservability:
        """Create the read-only receipts-backed view for this completed run."""
        return GraphObservability(graph, self.receipts, run_id=self.run_id)


NodeExecutor = Callable[[dict[str, Any]], NodeExecutionResult]
ConvergenceExecutor = Callable[
    [dict[str, Any], Mapping[str, int]], NodeExecutionResult
]


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _source_order(graph: Mapping[str, Any]) -> dict[str, int]:
    return {node["id"]: index for index, node in enumerate(graph["spec"]["nodes"])}


def _topological_order(graph: Mapping[str, Any]) -> tuple[str, ...]:
    """Cycle check helper; ready-set loop does not schedule from this order."""
    nodes = graph["spec"]["nodes"]
    source_order = _source_order(graph)
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


def _max_concurrency(graph: Mapping[str, Any]) -> int:
    limits = graph.get("spec", {}).get("resourceLimits") or {}
    raw = limits.get("maxConcurrency", 1)
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise SchedulerError(f"invalid maxConcurrency: {raw!r}") from exc
    if value < 1:
        raise SchedulerError(f"maxConcurrency must be >= 1, got {value}")
    return value


class GraphScheduler:
    """Execute validated graphs via a ready-set dispatch loop (PRD 269 R1/R2)."""

    def __init__(
        self,
        executor: NodeExecutor,
        *,
        receipts: ExecutionReceiptJournal,
        pools: ResourcePoolRegistry,
        convergence_executor: ConvergenceExecutor | None = None,
    ) -> None:
        self._executor = executor
        self._receipts = receipts
        self._pools = pools
        self._convergence_executor = convergence_executor

    def _validate_slot_requests(self, graph: Mapping[str, Any]) -> None:
        """Compile-time reject when slots exceed the effective pool limit."""
        for node in graph["spec"]["nodes"]:
            pool = PoolName(node["resources"]["pool"])
            slots = int(node["resources"]["slots"])
            if not self._pools.can_satisfy(pool, slots=slots):
                limit = self._pools.pools[pool].limit
                raise SchedulerError(
                    f"node {node['id']}: slots={slots} exceed pool "
                    f"{pool.value} limit={limit}"
                )

    def _resolve_policy(
        self,
        node_id: str,
        expected: Sequence[str],
        policies: Mapping[str, Mapping[str, Any] | FanInPolicy],
    ) -> FanInPolicy:
        raw_policy = policies.get(node_id)
        if isinstance(raw_policy, FanInPolicy):
            return raw_policy
        if raw_policy is not None:
            return parse_fanin_policy(dict(raw_policy))
        return _default_fanin(expected)

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
        _topological_order(graph)  # cycle check
        graph_hash = str(compiled["graphHash"])
        by_id = {node["id"]: node for node in graph["spec"]["nodes"]}
        predecessors = _predecessors(graph)
        source_order = _source_order(graph)
        policies = fanin_policies or {}
        max_conc = _max_concurrency(graph)
        self._validate_slot_requests(graph)

        claims = [
            NodeIsolationClaim(
                node_id=node_id,
                policy=parse_isolation_policy(by_id[node_id]["isolation"]),
                write_paths=frozenset((write_paths or {}).get(node_id, set())),
            )
            for node_id in by_id
        ]
        contention = tuple(analyze_write_contention(claims))

        outcomes: dict[str, NodeOutcome] = {}
        output_hashes: dict[str, str] = {}
        node_runs: dict[str, NodeRun] = {}
        persisted_receipts: list[dict[str, Any]] = []
        pending = set(by_id)

        def fanin_for(node_id: str) -> FanInResult:
            expected = predecessors[node_id]
            policy = self._resolve_policy(node_id, expected, policies)
            return evaluate_fanin(
                policy,
                (outcomes[item] for item in expected if item in outcomes),
                expected_nodes=expected,
            )

        def ready_set() -> list[str]:
            """Return ready node ids (source-order); record permanent fan-in blocks."""
            ready: list[str] = []
            blocked_now: list[str] = []
            for node_id in list(pending):
                if node_id in node_runs:
                    continue
                fanin = fanin_for(node_id)
                if fanin.unsettled:
                    # Settle-before-fire: not ready until every predecessor settles.
                    continue
                if fanin.halt:
                    outcomes[node_id] = NodeOutcome(node_id, success=False)
                    node_runs[node_id] = NodeRun(
                        node_id=node_id,
                        verdict="blocked",
                        dispatched=False,
                        fanin=fanin,
                        reason=fanin.reason,
                    )
                    blocked_now.append(node_id)
                    continue
                ready.append(node_id)
            for node_id in blocked_now:
                pending.discard(node_id)
            ready.sort(key=source_order.__getitem__)
            return ready

        def complete_replay(node_id: str, fanin: FanInResult) -> bool:
            idempotency_key = f"{run_id}:{graph_hash}:{node_id}"
            try:
                existing_receipt = self._receipts.get(node_id, idempotency_key)
            except KeyError:
                return False
            stored_hashes = existing_receipt.get("outputHashes") or []
            output_hash = str(stored_hashes[0]) if stored_hashes else None
            if output_hash is not None:
                output_hashes[node_id] = output_hash
            succeeded = existing_receipt.get("verdict") == "pass"
            outcomes[node_id] = NodeOutcome(node_id, success=succeeded)
            persisted_receipts.append(existing_receipt)
            node_runs[node_id] = NodeRun(
                node_id=node_id,
                verdict=str(existing_receipt.get("verdict") or "fail"),
                dispatched=False,
                fanin=fanin,
                output_hash=output_hash,
                reason="replayed complete receipt",
            )
            pending.discard(node_id)
            return True

        def execute_node(node_id: str, fanin: FanInResult, *, pool: PoolName, slots: int) -> None:
            """Execute with pool slots already acquired by the caller."""
            node = by_id[node_id]
            expected = predecessors[node_id]
            try:
                if node["kind"] == "convergence-loop" and self._convergence_executor:
                    result = self._convergence_executor(
                        dict(node),
                        dict(compiled["loopBounds"][node_id]),
                    )
                else:
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
                f"{run_id}:{graph_hash}:{node_id}",
                payload,
            )
            persisted_receipts.append(receipt)
            output_hashes[node_id] = output_hash
            outcomes[node_id] = NodeOutcome(node_id, success=result.success)
            node_runs[node_id] = NodeRun(
                node_id=node_id,
                verdict=result.verdict,
                dispatched=True,
                fanin=fanin,
                output_hash=output_hash,
            )
            pending.discard(node_id)

        # Ready-set loop: re-evaluate after each completion batch (R1).
        while pending:
            ready = ready_set()
            if not pending:
                break
            if not ready:
                raise SchedulerNoProgress(
                    sorted(pending, key=source_order.__getitem__),
                    reason="no-progress",
                )

            batch: list[tuple[str, FanInResult, PoolName, int]] = []
            parked: list[str] = []
            replayed = 0
            for node_id in ready:
                if len(batch) >= max_conc:
                    break
                fanin = fanin_for(node_id)
                if complete_replay(node_id, fanin):
                    replayed += 1
                    continue
                node = by_id[node_id]
                pool = PoolName(node["resources"]["pool"])
                slots = int(node["resources"]["slots"])
                try:
                    self._pools.acquire(pool, slots=slots)
                except PoolRequestUnsatisfiable as exc:
                    raise SchedulerError(
                        f"node {node_id}: unsatisfiable pool request at dispatch"
                    ) from exc
                except PoolExhausted:
                    parked.append(node_id)
                    continue
                batch.append((node_id, fanin, pool, slots))

            if not batch:
                if replayed:
                    continue
                if parked:
                    raise SchedulerNoProgress(parked, reason="pool-parked-no-progress")
                raise SchedulerNoProgress(
                    sorted(pending, key=source_order.__getitem__),
                    reason="no-progress",
                )

            # Slots held for the whole in-flight batch; release per completion.
            for node_id, fanin, pool, slots in batch:
                execute_node(node_id, fanin, pool=pool, slots=slots)

        leftovers = [node_id for node_id in by_id if node_id not in node_runs]
        if leftovers:
            raise SchedulerNoProgress(
                sorted(leftovers, key=source_order.__getitem__),
                reason="incomplete-nodes",
            )

        ordered_runs = tuple(
            node_runs[node_id]
            for node_id in sorted(node_runs, key=source_order.__getitem__)
        )
        verdict = (
            "pass"
            if all(item.verdict == "pass" for item in ordered_runs)
            else "fail"
        )
        return SchedulerRun(
            run_id=run_id,
            graph_hash=graph_hash,
            verdict=verdict,
            nodes=ordered_runs,
            receipts=tuple(persisted_receipts),
            contention_findings=contention,
            pool_snapshot=self._pools.snapshot(),
        )
