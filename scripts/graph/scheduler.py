#!/usr/bin/env python3
"""Internal-only runtime scheduler for validated WorkflowGraph documents."""
from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence, Set
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from graph.artifact_registry import PurityViolationError
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
    contends_with_inflight,
    parse_isolation_policy,
)
from graph.kernel_compiler import compile_workflow_graph
from graph.lineage import CacheKeyMaterial, compute_cache_key
from graph.observability import GraphObservability
from graph.resource_pools import (
    PoolExhausted,
    PoolName,
    PoolRequestUnsatisfiable,
    ResourcePoolRegistry,
)
from graph.scheduling_modes import (
    ExternalDispatchAuthorization,
    authorize_external_dispatch,
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


class SchedulerTimeout(SchedulerError):
    """Raised when node or run duration limits are exceeded."""


class CancelMode(str, Enum):
    """Failure semantics for concurrent in-flight mutating nodes (R16)."""

    CANCEL_AND_DRAIN = "cancel-and-drain"
    LET_SETTLE = "let-settle"


LeaseReleaser = Callable[[str], None]
CompensationHook = Callable[[str], None]
Clock = Callable[[], float]


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
    wrote: bool = False
    retry_only: bool = False
    prompt_version: str = "default"
    model_version: str = "default"
    tool_configuration: Mapping[str, Any] = field(default_factory=dict)
    policy_version: str = "default"
    credential_capabilities: tuple[str, ...] = ()
    scope_identity: str = "default"
    repository_identity: str = "default"
    trust_domain: str = "default"
    tool_binary_identity: str = "default"
    repo_state_identity: str = "default"

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
    cancel_mode: str | None = None

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


def _max_duration_seconds(graph: Mapping[str, Any]) -> int | None:
    limits = graph.get("spec", {}).get("resourceLimits") or {}
    if "maxDurationSeconds" not in limits:
        return None
    try:
        value = int(limits["maxDurationSeconds"])
    except (TypeError, ValueError) as exc:
        raise SchedulerError(
            f"invalid maxDurationSeconds: {limits['maxDurationSeconds']!r}"
        ) from exc
    if value < 1:
        raise SchedulerError(f"maxDurationSeconds must be >= 1, got {value}")
    return value


def _is_mutating(node: Mapping[str, Any], write_paths: Set[str] | frozenset[str]) -> bool:
    """Treat scoped/worktree writes or non-empty write paths as mutating (R16)."""
    execution = node.get("execution") or {}
    purity = execution.get("purity")
    if purity == "mutating":
        return True
    if purity == "read-only":
        return False
    write_scope = str((node.get("isolation") or {}).get("writeScope") or "none")
    if write_scope in {"scoped", "worktree"}:
        return True
    return bool(write_paths)


def _intent_payload(
    *,
    input_hashes: list[str],
    mutating: bool,
    timeout_seconds: int,
) -> dict[str, Any]:
    return {
        "model": "pending",
        "attempts": 1,
        "tokens": 0,
        "durationMs": 0,
        "inputHashes": input_hashes,
        "outputHashes": [],
        "verdict": "running",
        "coverage": {
            "intent": True,
            "mutating": mutating,
            "timeoutSeconds": timeout_seconds,
        },
    }


class GraphScheduler:
    """Execute validated graphs via a ready-set dispatch loop (PRD 269 R1/R2/R6/R16)."""

    def __init__(
        self,
        executor: NodeExecutor,
        *,
        receipts: ExecutionReceiptJournal,
        pools: ResourcePoolRegistry,
        convergence_executor: ConvergenceExecutor | None = None,
        lease_releaser: LeaseReleaser | None = None,
        compensation: CompensationHook | None = None,
        clock: Clock | None = None,
        cache_enabled: bool = True,
        cache_identity: Mapping[str, Any] | None = None,
    ) -> None:
        self._executor = executor
        self._receipts = receipts
        self._pools = pools
        self._convergence_executor = convergence_executor
        self._lease_releaser = lease_releaser
        self._compensation = compensation
        self._clock = clock or time.monotonic
        self._cache_enabled = cache_enabled
        self._cache_identity = dict(cache_identity or {})
        self._cancel_requested: CancelMode | None = None

    def request_cancel(
        self, mode: CancelMode = CancelMode.CANCEL_AND_DRAIN
    ) -> None:
        """Request cooperative cancellation with defined failure semantics (R16)."""
        self._cancel_requested = mode

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

    def _release_lease(self, node_id: str) -> None:
        if self._lease_releaser is None:
            return
        self._lease_releaser(node_id)

    def _compensate(self, node_id: str) -> None:
        if self._compensation is None:
            return
        self._compensation(node_id)

    def run(
        self,
        document: Mapping[str, Any],
        *,
        run_id: str,
        internal_only: bool = False,
        external_authorization: ExternalDispatchAuthorization | None = None,
        fanin_policies: Mapping[str, Mapping[str, Any] | FanInPolicy] | None = None,
        write_paths: Mapping[str, Set[str] | frozenset[str]] | None = None,
        kernel_options: Mapping[str, Any] | None = None,
    ) -> SchedulerRun:
        """Run a graph after all pre-dispatch checks have completed."""
        if not internal_only:
            authorize_external_dispatch(external_authorization)

        compiled = compile_workflow_graph(document, **dict(kernel_options or {}))
        graph = compiled["graph"]
        _topological_order(graph)  # cycle check
        graph_hash = str(compiled["graphHash"])
        by_id = {node["id"]: node for node in graph["spec"]["nodes"]}
        predecessors = _predecessors(graph)
        source_order = _source_order(graph)
        policies = fanin_policies or {}
        max_conc = _max_concurrency(graph)
        max_duration = _max_duration_seconds(graph)
        self._validate_slot_requests(graph)
        started_at = self._clock()
        applied_cancel: CancelMode | None = None

        claims_by_id = {
            node_id: NodeIsolationClaim(
                node_id=node_id,
                policy=parse_isolation_policy(by_id[node_id]["isolation"]),
                write_paths=frozenset((write_paths or {}).get(node_id, set())),
            )
            for node_id in by_id
        }
        claims = list(claims_by_id.values())
        # Whole-graph scan for observability; live dispatch gate uses in-flight union.
        contention = tuple(analyze_write_contention(claims))

        outcomes: dict[str, NodeOutcome] = {}
        output_hashes: dict[str, str] = {}
        node_runs: dict[str, NodeRun] = {}
        persisted_receipts: list[dict[str, Any]] = []
        pending = set(by_id)
        parked_ids: list[str] = []

        def fanin_for(node_id: str) -> FanInResult:
            expected = predecessors[node_id]
            policy = self._resolve_policy(node_id, expected, policies)
            return evaluate_fanin(
                policy,
                (outcomes[item] for item in expected if item in outcomes),
                expected_nodes=expected,
            )

        def flush_snapshot(queue: Sequence[str] = ()) -> None:
            self._receipts.write_pool_snapshot(
                self._pools.snapshot(),
                parked=parked_ids,
                queue=list(queue),
            )

        def mark_terminal(
            node_id: str,
            *,
            verdict: str,
            fanin: FanInResult,
            reason: str,
            dispatched: bool,
            output_hash: str | None = None,
            receipt: dict[str, Any] | None = None,
        ) -> None:
            if output_hash is not None:
                output_hashes[node_id] = output_hash
            outcomes[node_id] = NodeOutcome(
                node_id, success=(verdict == "pass")
            )
            if receipt is not None:
                persisted_receipts.append(receipt)
            node_runs[node_id] = NodeRun(
                node_id=node_id,
                verdict=verdict,
                dispatched=dispatched,
                fanin=fanin,
                output_hash=output_hash,
                reason=reason,
            )
            pending.discard(node_id)

        def cancel_node(
            node_id: str,
            fanin: FanInResult,
            *,
            pool: PoolName | None,
            slots: int,
            reason: str,
        ) -> None:
            if pool is not None:
                self._pools.release(pool, slots=slots)
            idempotency_key = f"{run_id}:{graph_hash}:{node_id}"
            node = by_id[node_id]
            mutating = _is_mutating(
                node, frozenset((write_paths or {}).get(node_id, set()))
            )
            timeout_seconds = int(node["resources"]["timeoutSeconds"])
            intent = _intent_payload(
                input_hashes=[
                    output_hashes[item]
                    for item in predecessors[node_id]
                    if item in output_hashes
                ],
                mutating=mutating,
                timeout_seconds=timeout_seconds,
            )
            # Ensure an intent exists then finish as cancelled (compensation path).
            try:
                self._receipts.begin(node_id, idempotency_key, intent)
            except Exception:
                pass
            receipt = self._receipts.finish(
                node_id,
                idempotency_key,
                {
                    **intent,
                    "verdict": "cancelled",
                    "coverage": {
                        **intent["coverage"],
                        "intent": False,
                        "cancelled": True,
                        "reason": reason,
                    },
                },
            )
            self._compensate(node_id)
            self._release_lease(node_id)
            mark_terminal(
                node_id,
                verdict="cancelled",
                fanin=fanin,
                reason=reason,
                dispatched=False,
                receipt=receipt,
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

        def _execution(node: Mapping[str, Any]) -> Mapping[str, Any]:
            raw = node.get("execution") or {}
            if isinstance(raw, Mapping) and raw.get("purity") and raw.get("cache"):
                return raw
            return {"purity": "mutating", "cache": "disabled"}

        def _input_hashes_for(node_id: str) -> dict[str, str]:
            return {
                item: output_hashes[item]
                for item in predecessors[node_id]
                if item in output_hashes
            }

        def _identity_fields(
            result: NodeExecutionResult | None = None,
        ) -> dict[str, Any]:
            base: dict[str, Any] = {
                "prompt_version": "default",
                "model_version": "default",
                "tool_configuration": {},
                "policy_version": "default",
                "credential_capabilities": (),
                "scope_identity": "default",
                "repository_identity": "default",
                "trust_domain": "default",
                "tool_binary_identity": "default",
                "repo_state_identity": "default",
            }
            base.update(self._cache_identity)
            if result is not None:
                base.update(
                    {
                        "prompt_version": result.prompt_version,
                        "model_version": (
                            result.model_version
                            if result.model_version != "default"
                            else result.model
                        ),
                        "tool_configuration": dict(result.tool_configuration),
                        "policy_version": result.policy_version,
                        "credential_capabilities": tuple(
                            result.credential_capabilities
                        ),
                        "scope_identity": result.scope_identity,
                        "repository_identity": result.repository_identity,
                        "trust_domain": result.trust_domain,
                        "tool_binary_identity": result.tool_binary_identity,
                        "repo_state_identity": result.repo_state_identity,
                    }
                )
                # Explicit scheduler identity wins over result defaults.
                base.update(self._cache_identity)
            return base

        def _cache_key_for(
            node: Mapping[str, Any], result: NodeExecutionResult | None = None
        ) -> str:
            identity = _identity_fields(result)
            return compute_cache_key(
                CacheKeyMaterial(
                    node_definition=dict(node),
                    input_hashes=_input_hashes_for(str(node["id"])),
                    prompt_version=str(identity["prompt_version"]),
                    model_version=str(identity["model_version"]),
                    tool_configuration=dict(identity["tool_configuration"]),
                    policy_version=str(identity["policy_version"]),
                    credential_capability_set=tuple(
                        identity.get("credential_capability_set")
                        or identity.get("credential_capabilities")
                        or ()
                    ),
                    resolved_scope_identity=str(
                        identity.get("resolved_scope_identity")
                        or identity.get("scope_identity")
                        or "default"
                    ),
                    repository_identity=str(identity["repository_identity"]),
                    trust_domain=str(identity["trust_domain"]),
                    tool_binary_identity=str(identity["tool_binary_identity"]),
                    repo_state_identity=str(identity["repo_state_identity"]),
                )
            )

        def try_cache_hit(node_id: str, fanin: FanInResult) -> bool:
            if not self._cache_enabled:
                return False
            node = by_id[node_id]
            if _execution(node).get("cache") != "content-addressed":
                return False
            cache_key = _cache_key_for(node)
            reusable = self._receipts.lookup_reusable_by_cache_key(cache_key)
            if reusable is None:
                return False
            idempotency_key = f"{run_id}:{graph_hash}:{node_id}"
            receipt = self._receipts.record_cache_hit(
                node_id,
                idempotency_key,
                source=reusable,
                cache_key=cache_key,
            )
            stored_hashes = receipt.get("outputHashes") or []
            output_hash = str(stored_hashes[0]) if stored_hashes else None
            if output_hash is not None:
                output_hashes[node_id] = output_hash
            outcomes[node_id] = NodeOutcome(node_id, success=True)
            persisted_receipts.append(receipt)
            node_runs[node_id] = NodeRun(
                node_id=node_id,
                verdict="pass",
                dispatched=False,
                fanin=fanin,
                output_hash=output_hash,
                reason="cache-hit",
            )
            pending.discard(node_id)
            return True


        def execute_node(
            node_id: str,
            fanin: FanInResult,
            *,
            pool: PoolName,
            slots: int,
        ) -> None:
            """Execute with pool slots already acquired and begin() intent written."""
            node = by_id[node_id]
            expected = predecessors[node_id]
            timeout_seconds = int(node["resources"]["timeoutSeconds"])
            node_started = self._clock()
            try:
                if max_duration is not None and (self._clock() - started_at) > max_duration:
                    raise SchedulerTimeout(
                        f"run exceeded maxDurationSeconds={max_duration}"
                    )
                if node["kind"] == "convergence-loop" and self._convergence_executor:
                    result = self._convergence_executor(
                        dict(node),
                        dict(compiled["loopBounds"][node_id]),
                    )
                else:
                    result = self._executor(dict(node))
                elapsed = self._clock() - node_started
                if elapsed > timeout_seconds:
                    raise SchedulerTimeout(
                        f"node {node_id} exceeded timeoutSeconds={timeout_seconds}"
                    )
            except BaseException:
                self._pools.release(pool, slots=slots)
                self._release_lease(node_id)
                flush_snapshot()
                raise
            else:
                self._pools.release(pool, slots=slots)

            if not isinstance(result, NodeExecutionResult):
                raise SchedulerError(
                    f"executor returned invalid result for node {node_id}"
                )

            # Honor declared timeout against reported duration as well.
            if result.duration_ms > timeout_seconds * 1000:
                reason = f"timeoutSeconds={timeout_seconds}"
                receipt = self._receipts.finish(
                    node_id,
                    f"{run_id}:{graph_hash}:{node_id}",
                    {
                        "model": result.model,
                        "attempts": result.attempts,
                        "tokens": result.tokens,
                        "durationMs": result.duration_ms,
                        "inputHashes": [
                            output_hashes[item]
                            for item in expected
                            if item in output_hashes
                        ],
                        "outputHashes": [],
                        "verdict": "fail",
                        "coverage": {
                            **dict(result.coverage),
                            "timeout": True,
                            "reason": reason,
                        },
                    },
                )
                self._compensate(node_id)
                self._release_lease(node_id)
                mark_terminal(
                    node_id,
                    verdict="fail",
                    fanin=fanin,
                    reason=reason,
                    dispatched=True,
                    receipt=receipt,
                )
                flush_snapshot()
                return

            execution = _execution(node)
            if execution.get("purity") == "read-only" and result.wrote:
                raise PurityViolationError(
                    f"read-only node {node_id} produced writes; failing closed"
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
            if result.retry_only:
                payload["retryOnly"] = True
            cache_key = None
            if (
                self._cache_enabled
                and execution.get("cache") == "content-addressed"
                and result.success
                and not result.retry_only
            ):
                cache_key = _cache_key_for(node, result)
            receipt = self._receipts.finish(
                node_id,
                f"{run_id}:{graph_hash}:{node_id}",
                payload,
                cache_key=cache_key,
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
            self._release_lease(node_id)
            flush_snapshot()

        # Ready-set loop: re-evaluate after each completion batch (R1).
        while pending:
            if max_duration is not None and (self._clock() - started_at) > max_duration:
                for node_id in sorted(pending, key=source_order.__getitem__):
                    cancel_node(
                        node_id,
                        fanin_for(node_id),
                        pool=None,
                        slots=0,
                        reason=f"maxDurationSeconds={max_duration}",
                    )
                applied_cancel = CancelMode.CANCEL_AND_DRAIN
                break

            if self._cancel_requested is CancelMode.CANCEL_AND_DRAIN:
                for node_id in sorted(pending, key=source_order.__getitem__):
                    cancel_node(
                        node_id,
                        fanin_for(node_id),
                        pool=None,
                        slots=0,
                        reason="cancel-and-drain",
                    )
                applied_cancel = CancelMode.CANCEL_AND_DRAIN
                break

            if self._cancel_requested is CancelMode.LET_SETTLE:
                # No new admissions once let-settle is requested and nothing is
                # mid-batch; pending nodes that never started fail the run.
                applied_cancel = CancelMode.LET_SETTLE
                for node_id in sorted(pending, key=source_order.__getitem__):
                    cancel_node(
                        node_id,
                        fanin_for(node_id),
                        pool=None,
                        slots=0,
                        reason="let-settle-no-new-admission",
                    )
                break

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
                if try_cache_hit(node_id, fanin):
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
                gate_hits = contends_with_inflight(
                    claims_by_id[node_id],
                    [claims_by_id[nid] for nid, _, _, _ in batch],
                )
                if gate_hits:
                    self._pools.release(pool, slots=slots)
                    parked.append(node_id)
                    continue
                batch.append((node_id, fanin, pool, slots))

            parked_ids = list(parked)
            if not batch:
                flush_snapshot(queue=ready)
                if replayed:
                    continue
                if parked:
                    raise SchedulerNoProgress(parked, reason="pool-parked-no-progress")
                raise SchedulerNoProgress(
                    sorted(pending, key=source_order.__getitem__),
                    reason="no-progress",
                )

            # Pre-dispatch begin() for every admitted node (mutating intents first).
            for node_id, fanin, pool, slots in batch:
                node = by_id[node_id]
                mutating = _is_mutating(
                    node, frozenset((write_paths or {}).get(node_id, set()))
                )
                timeout_seconds = int(node["resources"]["timeoutSeconds"])
                intent = _intent_payload(
                    input_hashes=[
                        output_hashes[item]
                        for item in predecessors[node_id]
                        if item in output_hashes
                    ],
                    mutating=mutating,
                    timeout_seconds=timeout_seconds,
                )
                self._receipts.begin(
                    node_id,
                    f"{run_id}:{graph_hash}:{node_id}",
                    intent,
                )
            flush_snapshot(queue=[node_id for node_id, _, _, _ in batch])

            # Slots held for the whole in-flight batch; release per completion/crash.
            for index, (node_id, fanin, pool, slots) in enumerate(batch):
                # Mid-batch cancel-and-drain: drain remaining without executing.
                if (
                    self._cancel_requested is CancelMode.CANCEL_AND_DRAIN
                    and index > 0
                ):
                    applied_cancel = CancelMode.CANCEL_AND_DRAIN
                    cancel_node(
                        node_id,
                        fanin,
                        pool=pool,
                        slots=slots,
                        reason="cancel-and-drain",
                    )
                    for rest_id, rest_fanin, rest_pool, rest_slots in batch[index + 1 :]:
                        cancel_node(
                            rest_id,
                            rest_fanin,
                            pool=rest_pool,
                            slots=rest_slots,
                            reason="cancel-and-drain",
                        )
                    break
                try:
                    execute_node(node_id, fanin, pool=pool, slots=slots)
                except BaseException:
                    # Crash compensation: release remaining leases/slots (R16).
                    for rest_id, _rest_fanin, rest_pool, rest_slots in batch[
                        index + 1 :
                    ]:
                        self._pools.release(rest_pool, slots=rest_slots)
                        self._release_lease(rest_id)
                    flush_snapshot()
                    raise
                if self._cancel_requested is CancelMode.LET_SETTLE:
                    applied_cancel = CancelMode.LET_SETTLE
                    # Finish remaining already-admitted batch (let-settle).
                    for rest_id, rest_fanin, rest_pool, rest_slots in batch[
                        index + 1 :
                    ]:
                        execute_node(
                            rest_id, rest_fanin, pool=rest_pool, slots=rest_slots
                        )
                    for node_left in sorted(pending, key=source_order.__getitem__):
                        cancel_node(
                            node_left,
                            fanin_for(node_left),
                            pool=None,
                            slots=0,
                            reason="let-settle-no-new-admission",
                        )
                    break

        leftovers = [node_id for node_id in by_id if node_id not in node_runs]
        if leftovers:
            # Fail closed: every node must terminal or the run fails (R16).
            for node_id in leftovers:
                cancel_node(
                    node_id,
                    fanin_for(node_id),
                    pool=None,
                    slots=0,
                    reason="incomplete-nodes",
                )

        ordered_runs = tuple(
            node_runs[node_id]
            for node_id in sorted(node_runs, key=source_order.__getitem__)
        )
        flush_snapshot()
        # Persist lightweight telemetry for teardown durability (R13).
        self._receipts.write_telemetry(
            {
                "nodeCount": len(ordered_runs),
                "cancelled": sum(
                    1 for item in ordered_runs if item.verdict == "cancelled"
                ),
                "failed": sum(1 for item in ordered_runs if item.verdict == "fail"),
                "passed": sum(1 for item in ordered_runs if item.verdict == "pass"),
            }
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
            cancel_mode=None if applied_cancel is None else applied_cancel.value,
        )
