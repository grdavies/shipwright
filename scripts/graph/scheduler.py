#!/usr/bin/env python3
"""Internal-only runtime scheduler for validated WorkflowGraph documents."""
from __future__ import annotations

import hashlib
import json
import queue
import threading
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
from graph.timing_events import TimingCategory, TimingEventRecorder
from graph.cache_store import (
    CacheScope,
    CanonicalCacheStore,
    node_cache_eligible,
)
from graph.execution_backend import (
    ExecutionBackend,
    ExecutionHandle,
    HostAdjudicationContext,
    HostExecutionHints,
    LocalSyncExecutionBackend,
    PollPhase,
    SubmitRequest,
    adjudicate_terminal_envelope,
)
from graph.worktree_integration import (
    IntegrationTransitionResult,
    WorktreeIntegrationBarrier,
    WorktreeIntegrationError,
    extract_worktree_manifest,
    requires_worktree_integration,
)
from graph.detectors.redetect import (
    RequirementSetSnapshot,
    RedetectGateVerdict,
    evaluate_redetect_gate,
    merge_gate_redetect,
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


@dataclass
class _InflightWork:
    """One node admitted and executing on a worker thread."""

    node_id: str
    fanin: FanInResult
    pool: PoolName
    slots: int
    handle: ExecutionHandle | None = None


@dataclass
class _CompletionEvent:
    """Marshalled completion from a worker thread to the owning loop (R17)."""

    node_id: str
    fanin: FanInResult
    pool: PoolName
    slots: int
    result: NodeExecutionResult | None = None
    error: BaseException | None = None
    cancelled: bool = False
    cancel_reason: str = ""


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
class RedetectContext:
    """Optional realized-diff redetect binding for scheduler runs (PRD 272 R4)."""

    changed_paths: tuple[str, ...]
    dispatched: RequirementSetSnapshot
    satisfied_capability_ids: frozenset[str]


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
    timing_events: tuple[dict[str, Any], ...] = ()
    redetect: RedetectGateVerdict | None = None

    def observability(self, graph: Mapping[str, Any]) -> GraphObservability:
        """Create the read-only receipts-backed view for this completed run."""
        return GraphObservability(
            graph,
            self.receipts,
            run_id=self.run_id,
            timing_events=self.timing_events,
        )


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
        cache_store: CanonicalCacheStore | None = None,
        cache_scope: CacheScope = CacheScope.RUN,
        backend: ExecutionBackend | None = None,
    ) -> None:
        self._executor = executor
        self._backend: ExecutionBackend = backend or LocalSyncExecutionBackend(
            executor, clock=clock
        )
        self._receipts = receipts
        self._pools = pools
        self._convergence_executor = convergence_executor
        self._lease_releaser = lease_releaser
        self._compensation = compensation
        self._clock = clock or time.monotonic
        self._cache_enabled = cache_enabled
        self._cache_identity = dict(cache_identity or {})
        self._cache_store = cache_store
        self._cache_scope = cache_scope
        self._cancel_requested: CancelMode | None = None
        self._event_queue: queue.SimpleQueue[_CompletionEvent] = queue.SimpleQueue()
        self._owning_loop_transitions = 0
        self._state_owner_thread: int | None = None

    @property
    def owning_loop_transitions(self) -> int:
        """Count of scheduler state transitions on the owning loop (tests / R17)."""
        return self._owning_loop_transitions

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

    def _run_via_backend(
        self,
        node: Mapping[str, Any],
        *,
        idempotency_key: str,
        input_hashes: list[str],
        mutating: bool,
        purity: str,
        capability_token: str = "",
    ) -> NodeExecutionResult:
        """Dispatch through ExecutionBackend; host adjudicates terminal envelopes (R9/R10)."""
        started = self._clock()
        request = SubmitRequest(
            idempotency_key=idempotency_key,
            node=dict(node),
            capability_token=capability_token,
            input_hashes=tuple(input_hashes),
            host_hints=HostExecutionHints(mutating=mutating, purity=purity),
        )
        submit = self._backend.submit(request)
        handle = submit.handle
        poll = self._backend.poll(handle)
        while poll.phase not in (PollPhase.TERMINAL, PollPhase.CANCEL_ACKNOWLEDGED):
            poll = self._backend.poll(handle)
        terminal = self._backend.result(handle)
        host = HostAdjudicationContext(
            node_id=str(node["id"]),
            idempotency_key=idempotency_key,
            mutating=mutating,
            purity=purity,
            cache_identity=self._cache_identity,
            started_at_monotonic=started,
            input_hashes=tuple(input_hashes),
        )
        return adjudicate_terminal_envelope(host, terminal, clock=self._clock).to_node_execution_result()

    def _compensate(self, node_id: str) -> None:
        if self._compensation is None:
            return
        self._compensation(node_id)

    def _assert_owning_loop(self) -> None:
        owner = self._state_owner_thread
        if owner is not None and threading.get_ident() != owner:
            raise SchedulerError("scheduler state mutation off owning loop")

    def _bump_owning_loop(self) -> None:
        self._assert_owning_loop()
        self._owning_loop_transitions += 1

    def _inflight_claims(
        self,
        inflight: Mapping[str, _InflightWork],
        claims_by_id: Mapping[str, NodeIsolationClaim],
    ) -> list[NodeIsolationClaim]:
        return [claims_by_id[node_id] for node_id in sorted(inflight)]

    def _fence_cancel_handle(
        self,
        handle: ExecutionHandle,
        *,
        reason: str,
    ) -> PollPhase:
        """cancel-requested → ack/terminated before release (R3)."""
        poll = self._backend.cancel(handle)
        while poll.phase not in (PollPhase.TERMINAL, PollPhase.CANCEL_ACKNOWLEDGED):
            poll = self._backend.poll(handle)
        return poll.phase

    def _run_node_worker(
        self,
        node: Mapping[str, Any],
        *,
        work: _InflightWork,
        run_id: str,
        graph_hash: str,
        predecessors: Mapping[str, tuple[str, ...]],
        output_hashes: Mapping[str, str],
        write_paths: Mapping[str, Set[str] | frozenset[str]] | None,
        compiled: Mapping[str, Any],
        started_at: float,
        max_duration: int | None,
    ) -> NodeExecutionResult:
        node_id = str(node["id"])
        timeout_seconds = int(node["resources"]["timeoutSeconds"])
        node_started = self._clock()
        idempotency_key = f"{run_id}:{graph_hash}:{node_id}"
        mutating = _is_mutating(
            node, frozenset((write_paths or {}).get(node_id, set()))
        )
        execution = node.get("execution") or {}
        if isinstance(execution, Mapping) and execution.get("purity") and execution.get(
            "cache"
        ):
            exec_blob = execution
        else:
            exec_blob = {"purity": "mutating", "cache": "disabled"}
        purity = str(
            exec_blob.get("purity") or ("mutating" if mutating else "read-only")
        )
        predecessor_hashes = [
            output_hashes[item]
            for item in predecessors[node_id]
            if item in output_hashes
        ]
        if max_duration is not None and (self._clock() - started_at) > max_duration:
            raise SchedulerTimeout(f"run exceeded maxDurationSeconds={max_duration}")
        if node["kind"] == "convergence-loop" and self._convergence_executor:
            result = self._convergence_executor(
                dict(node),
                dict(compiled["loopBounds"][node_id]),
            )
        else:
            submit = self._backend.submit(
                SubmitRequest(
                    idempotency_key=idempotency_key,
                    node=dict(node),
                    capability_token="",
                    input_hashes=tuple(predecessor_hashes),
                    host_hints=HostExecutionHints(mutating=mutating, purity=purity),
                )
            )
            handle = submit.handle
            work.handle = handle
            poll = self._backend.poll(handle)
            while poll.phase not in (
                PollPhase.TERMINAL,
                PollPhase.CANCEL_ACKNOWLEDGED,
            ):
                if self._cancel_requested is CancelMode.CANCEL_AND_DRAIN:
                    self._backend.cancel(handle)
                poll = self._backend.poll(handle)
            terminal = self._backend.result(handle)
            host = HostAdjudicationContext(
                node_id=node_id,
                idempotency_key=idempotency_key,
                mutating=mutating,
                purity=purity,
                cache_identity=self._cache_identity,
                started_at_monotonic=node_started,
                input_hashes=tuple(predecessor_hashes),
            )
            result = adjudicate_terminal_envelope(
                host, terminal, clock=self._clock
            ).to_node_execution_result()
            advisory_ms = int(terminal.report.duration_ms or 0)
            if advisory_ms > result.duration_ms:
                result = NodeExecutionResult(
                    verdict=result.verdict,
                    output=result.output,
                    model=result.model,
                    attempts=result.attempts,
                    tokens=result.tokens,
                    duration_ms=advisory_ms,
                    coverage=dict(result.coverage),
                    wrote=result.wrote,
                    retry_only=result.retry_only,
                    prompt_version=result.prompt_version,
                    model_version=result.model_version,
                    tool_configuration=result.tool_configuration,
                    policy_version=result.policy_version,
                    credential_capabilities=result.credential_capabilities,
                    scope_identity=result.scope_identity,
                    repository_identity=result.repository_identity,
                    trust_domain=result.trust_domain,
                    tool_binary_identity=result.tool_binary_identity,
                    repo_state_identity=result.repo_state_identity,
                )
            if poll.phase is PollPhase.CANCEL_ACKNOWLEDGED:
                result = NodeExecutionResult(
                    verdict="cancelled",
                    output=result.output,
                    model=result.model,
                    attempts=result.attempts,
                    tokens=result.tokens,
                    duration_ms=result.duration_ms,
                    coverage={
                        **dict(result.coverage),
                        "cancelled": True,
                        "reason": "cancel-acknowledged",
                    },
                )
        elapsed = self._clock() - node_started
        if elapsed > timeout_seconds:
            raise SchedulerTimeout(
                f"node {node_id} exceeded timeoutSeconds={timeout_seconds}"
            )
        if not isinstance(result, NodeExecutionResult):
            raise SchedulerError(
                f"executor returned invalid result for node {node_id}"
            )
        return result

    def _start_worker(
        self,
        work: _InflightWork,
        *,
        node: Mapping[str, Any],
        run_id: str,
        graph_hash: str,
        predecessors: Mapping[str, tuple[str, ...]],
        output_hashes: Mapping[str, str],
        write_paths: Mapping[str, Set[str] | frozenset[str]] | None,
        compiled: Mapping[str, Any],
        started_at: float,
        max_duration: int | None,
    ) -> None:
        def _task() -> None:
            try:
                result = self._run_node_worker(
                    node,
                    work=work,
                    run_id=run_id,
                    graph_hash=graph_hash,
                    predecessors=predecessors,
                    output_hashes=output_hashes,
                    write_paths=write_paths,
                    compiled=compiled,
                    started_at=started_at,
                    max_duration=max_duration,
                )
                self._event_queue.put(
                    _CompletionEvent(
                        node_id=work.node_id,
                        fanin=work.fanin,
                        pool=work.pool,
                        slots=work.slots,
                        result=result,
                    )
                )
            except BaseException as exc:
                self._event_queue.put(
                    _CompletionEvent(
                        node_id=work.node_id,
                        fanin=work.fanin,
                        pool=work.pool,
                        slots=work.slots,
                        error=exc,
                    )
                )

        threading.Thread(target=_task, daemon=True).start()

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
        redetect_context: RedetectContext | None = None,
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
        timing = TimingEventRecorder(
            self._receipts,
            clock=self._clock,
            run_started_monotonic=started_at,
        )
        node_pending_since: dict[str, float] = {
            node_id: started_at for node_id in by_id
        }
        node_fanin_recorded: set[str] = set()
        node_parked: dict[str, tuple[str, float]] = {}

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
        integration_barrier = WorktreeIntegrationBarrier(
            source_order, clock=self._clock
        )
        awaiting_integration: set[str] = set()
        redetect_state = (
            redetect_context.dispatched if redetect_context is not None else None
        )
        redetect_verdict: RedetectGateVerdict | None = None
        redetect_failure: str | None = None

        def fanin_for(node_id: str) -> FanInResult:
            expected = predecessors[node_id]
            policy = self._resolve_policy(node_id, expected, policies)
            return evaluate_fanin(
                policy,
                (outcomes[item] for item in expected if item in outcomes),
                expected_nodes=expected,
            )

        def flush_snapshot(queue: Sequence[str] = ()) -> None:
            bk_start = self._clock()
            self._receipts.write_pool_snapshot(
                self._pools.snapshot(),
                parked=parked_ids,
                queue=list(queue),
            )
            timing.record_bookkeeping(
                int((self._clock() - bk_start) * 1000), detail="pool-snapshot"
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
            settled: bool = True,
        ) -> None:
            if output_hash is not None:
                output_hashes[node_id] = output_hash
            outcomes[node_id] = NodeOutcome(
                node_id,
                success=(verdict == "pass"),
                settled=settled,
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
                self._pools.release(pool, slots=slots, node_id=node_id)
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

        def _record_park_end(node_id: str) -> None:
            parked = node_parked.pop(node_id, None)
            if parked is None:
                return
            category_str, park_start = parked
            duration_ms = int((self._clock() - park_start) * 1000)
            if duration_ms <= 0:
                return
            timing.record_interval(
                node_id,
                TimingCategory(category_str),
                duration_ms=duration_ms,
                monotonic_start_ms=int((park_start - started_at) * 1000),
            )

        def _park_node(node_id: str, category: TimingCategory) -> None:
            if node_id in node_parked:
                return
            node_parked[node_id] = (category.value, self._clock())

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
                if node_id not in node_fanin_recorded:
                    wait_ms = int(
                        (self._clock() - node_pending_since[node_id]) * 1000
                    )
                    if wait_ms > 0:
                        timing.record_interval(
                            node_id,
                            TimingCategory.FANIN_WAIT,
                            duration_ms=wait_ms,
                            monotonic_start_ms=int(
                                (node_pending_since[node_id] - started_at) * 1000
                            ),
                        )
                    node_fanin_recorded.add(node_id)
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
            base: dict[str, Any] = {}
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
                    prompt_version=str(identity.get("prompt_version") or ""),
                    model_version=str(identity.get("model_version") or ""),
                    tool_configuration=dict(identity.get("tool_configuration") or {}),
                    policy_version=str(identity.get("policy_version") or ""),
                    credential_capability_set=tuple(
                        identity.get("credential_capability_set")
                        or identity.get("credential_capabilities")
                        or ()
                    ),
                    resolved_scope_identity=str(
                        identity.get("resolved_scope_identity")
                        or identity.get("scope_identity")
                        or ""
                    ),
                    repository_identity=str(identity.get("repository_identity") or ""),
                    trust_domain=str(identity.get("trust_domain") or ""),
                    tool_binary_identity=str(identity.get("tool_binary_identity") or ""),
                    repo_state_identity=str(identity.get("repo_state_identity") or ""),
                )
            )

        def try_cache_hit(node_id: str, fanin: FanInResult) -> bool:
            if not self._cache_enabled:
                return False
            node = by_id[node_id]
            if _execution(node).get("cache") != "content-addressed":
                return False
            identity = _identity_fields()
            if not node_cache_eligible(node, identity):
                return False
            cache_key = _cache_key_for(node)
            hit = None
            if self._cache_store is not None:
                hit = self._cache_store.lookup(cache_key, run_id=run_id)
            if hit is None:
                return False
            idempotency_key = f"{run_id}:{graph_hash}:{node_id}"
            receipt = self._receipts.record_cache_hit(
                node_id,
                idempotency_key,
                source=hit.source_receipt,
                cache_key=cache_key,
                original_run_id=hit.original_run_id,
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


        inflight: dict[str, _InflightWork] = {}

        def _release_inflight(work: _InflightWork) -> None:
            self._pools.release(
                work.pool, slots=work.slots, node_id=work.node_id
            )

        def _apply_node_result(
            node_id: str,
            fanin: FanInResult,
            result: NodeExecutionResult,
            work: _InflightWork,
        ) -> None:
            """Apply a terminal worker result; idempotent when receipt already complete."""
            idempotency_key = f"{run_id}:{graph_hash}:{node_id}"
            try:
                existing = self._receipts.get(node_id, idempotency_key)
                if existing.get("state") == "complete":
                    stored_hashes = existing.get("outputHashes") or []
                    output_hash = str(stored_hashes[0]) if stored_hashes else None
                    mark_terminal(
                        node_id,
                        verdict=str(existing.get("verdict") or "fail"),
                        fanin=fanin,
                        reason="replayed complete receipt",
                        dispatched=True,
                        output_hash=output_hash,
                        receipt=existing,
                    )
                    _release_inflight(work)
                    self._release_lease(node_id)
                    return
            except KeyError:
                pass

            if result.duration_ms > 0:
                end_mono = int((self._clock() - started_at) * 1000)
                timing.record_interval(
                    node_id,
                    TimingCategory.EXECUTION,
                    duration_ms=result.duration_ms,
                    monotonic_start_ms=max(0, end_mono - result.duration_ms),
                )

            node = by_id[node_id]
            expected = predecessors[node_id]
            timeout_seconds = int(node["resources"]["timeoutSeconds"])

            if result.duration_ms > timeout_seconds * 1000:
                reason = f"timeoutSeconds={timeout_seconds}"
                receipt = self._receipts.finish(
                    node_id,
                    idempotency_key,
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
                _release_inflight(work)
                self._release_lease(node_id)
                mark_terminal(
                    node_id,
                    verdict="fail",
                    fanin=fanin,
                    reason=reason,
                    dispatched=True,
                    receipt=receipt,
                )
                return

            execution = _execution(node)
            if execution.get("purity") == "read-only" and result.wrote:
                _release_inflight(work)
                self._release_lease(node_id)
                raise PurityViolationError(
                    f"read-only node {node_id} produced writes; failing closed"
                )

            if result.verdict == "cancelled":
                receipt = self._receipts.finish(
                    node_id,
                    idempotency_key,
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
                        "verdict": "cancelled",
                        "coverage": {
                            **dict(result.coverage),
                            "cancelled": True,
                            "reason": str(
                                result.coverage.get("reason") or "cancelled"
                            ),
                        },
                    },
                )
                self._compensate(node_id)
                _release_inflight(work)
                self._release_lease(node_id)
                mark_terminal(
                    node_id,
                    verdict="cancelled",
                    fanin=fanin,
                    reason=str(result.coverage.get("reason") or "cancelled"),
                    dispatched=True,
                    receipt=receipt,
                )
                return

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
                idempotency_key,
                payload,
                cache_key=cache_key,
            )
            if (
                cache_key
                and self._cache_store is not None
                and node_cache_eligible(node, _identity_fields(result))
            ):
                material = CacheKeyMaterial(
                    node_definition=dict(node),
                    input_hashes=_input_hashes_for(node_id),
                    prompt_version=str(_identity_fields(result).get("prompt_version") or ""),
                    model_version=str(_identity_fields(result).get("model_version") or ""),
                    tool_configuration=dict(
                        _identity_fields(result).get("tool_configuration") or {}
                    ),
                    policy_version=str(_identity_fields(result).get("policy_version") or ""),
                    credential_capability_set=tuple(
                        _identity_fields(result).get("credential_capabilities") or ()
                    ),
                    resolved_scope_identity=str(
                        _identity_fields(result).get("scope_identity") or ""
                    ),
                    repository_identity=str(
                        _identity_fields(result).get("repository_identity") or ""
                    ),
                    trust_domain=str(_identity_fields(result).get("trust_domain") or ""),
                    tool_binary_identity=str(
                        _identity_fields(result).get("tool_binary_identity") or ""
                    ),
                    repo_state_identity=str(
                        _identity_fields(result).get("repo_state_identity") or ""
                    ),
                )
                artifacts = (
                    {
                        "artifactId": output_hash,
                        "schema": "graph/output@v1",
                        "content": result.output,
                        "producingNode": node_id,
                        "inputRevision": output_hash,
                        "verificationEvidence": [],
                    },
                )
                try:
                    self._cache_store.put(
                        material=material,
                        source_receipt=receipt,
                        artifacts=artifacts,
                        run_id=run_id,
                    )
                except Exception:
                    pass
            persisted_receipts.append(receipt)
            _release_inflight(work)
            claim = claims_by_id[node_id]
            node_mutating = _is_mutating(
                node, frozenset((write_paths or {}).get(node_id, set()))
            )
            if requires_worktree_integration(claim.policy, mutating=node_mutating):
                if not result.success:
                    self._release_lease(node_id)
                    mark_terminal(
                        node_id,
                        verdict=result.verdict,
                        fanin=fanin,
                        reason="",
                        dispatched=True,
                        output_hash=output_hash,
                        receipt=receipt,
                    )
                    return
                manifest = None
                try:
                    manifest = extract_worktree_manifest(result.coverage)
                except WorktreeIntegrationError as exc:
                    reason = str(exc)
                    self._compensate(node_id)
                    self._release_lease(node_id)
                    mark_terminal(
                        node_id,
                        verdict="fail",
                        fanin=fanin,
                        reason=reason,
                        dispatched=True,
                        output_hash=output_hash,
                        receipt=receipt,
                    )
                    return
                if manifest is None:
                    self._release_lease(node_id)
                    mark_terminal(
                        node_id,
                        verdict=result.verdict,
                        fanin=fanin,
                        reason="",
                        dispatched=True,
                        output_hash=output_hash,
                        receipt=receipt,
                    )
                    return
                integration_barrier.enqueue(node_id, manifest)
                awaiting_integration.add(node_id)
                mark_terminal(
                    node_id,
                    verdict="pass",
                    fanin=fanin,
                    reason="awaiting-worktree-integration",
                    dispatched=True,
                    output_hash=output_hash,
                    receipt=receipt,
                    settled=False,
                )
                _drain_worktree_integration()
                return
            self._release_lease(node_id)
            mark_terminal(
                node_id,
                verdict=result.verdict,
                fanin=fanin,
                reason="",
                dispatched=True,
                output_hash=output_hash,
                receipt=receipt,
            )

        def _apply_integration_transition(
            transition: IntegrationTransitionResult,
        ) -> None:
            node_id = transition.node_id
            awaiting_integration.discard(node_id)
            fanin = fanin_for(node_id)
            existing = node_runs.get(node_id)
            if transition.conflict or transition.verdict != "pass":
                self._compensate(node_id)
                self._release_lease(node_id)
                outcomes[node_id] = NodeOutcome(
                    node_id, success=False, settled=True
                )
                if existing is not None:
                    node_runs[node_id] = NodeRun(
                        node_id=node_id,
                        verdict="fail",
                        dispatched=existing.dispatched,
                        fanin=fanin,
                        output_hash=existing.output_hash,
                        reason=transition.reason,
                    )
                return
            self._release_lease(node_id)
            outcomes[node_id] = NodeOutcome(
                node_id, success=True, settled=True
            )
            if existing is not None:
                node_runs[node_id] = NodeRun(
                    node_id=node_id,
                    verdict="pass",
                    dispatched=existing.dispatched,
                    fanin=fanin,
                    output_hash=existing.output_hash,
                    reason=transition.reason,
                )

        def _run_barrier_redetect(manifest_paths: tuple[str, ...]) -> None:
            nonlocal redetect_state, redetect_verdict, redetect_failure
            if redetect_context is None or redetect_state is None:
                return
            combined = tuple(
                sorted(set(redetect_context.changed_paths + manifest_paths))
            )
            verdict = evaluate_redetect_gate(
                changed_paths=combined,
                dispatched=redetect_state,
                satisfied_capability_ids=redetect_context.satisfied_capability_ids,
                gate="barrier",
            )
            redetect_verdict = verdict
            if verdict.verdict != "pass":
                redetect_failure = verdict.reason
                return
            redetect_state = verdict.dispatched

        def _drain_worktree_integration() -> None:
            if not integration_barrier.has_pending():
                return
            transitions = integration_barrier.drain()
            history_tail = integration_barrier.history[-len(transitions) :]
            manifest_paths = tuple(
                sorted(
                    {
                        path
                        for item in history_tail
                        for path in item.get("manifestPaths", ())
                    }
                )
            )
            if manifest_paths:
                _run_barrier_redetect(manifest_paths)
            for transition in transitions:
                _apply_integration_transition(transition)
            flush_snapshot()

        def _process_completion(event: _CompletionEvent) -> None:
            self._bump_owning_loop()
            work = inflight.pop(event.node_id, None)
            if work is None:
                return
            node_id = event.node_id
            fanin = event.fanin
            if event.error is not None:
                _release_inflight(work)
                self._release_lease(node_id)
                flush_snapshot()
                if isinstance(event.error, BaseException):
                    raise event.error
                raise SchedulerError(str(event.error))
            if event.cancelled:
                result = event.result or NodeExecutionResult(
                    verdict="cancelled",
                    coverage={
                        "cancelled": True,
                        "reason": event.cancel_reason or "cancelled",
                    },
                )
                _apply_node_result(node_id, fanin, result, work)
                return
            if event.result is None:
                _release_inflight(work)
                self._release_lease(node_id)
                raise SchedulerError(
                    f"completion event missing result for node {node_id}"
                )
            _apply_node_result(node_id, fanin, event.result, work)

        def _cancel_pending(reason: str) -> None:
            for node_id in sorted(list(pending), key=source_order.__getitem__):
                if node_id in inflight:
                    continue
                fanin = fanin_for(node_id)
                if fanin.unsettled or fanin.halt:
                    continue
                cancel_node(
                    node_id,
                    fanin,
                    pool=None,
                    slots=0,
                    reason=reason,
                )

        def _fence_inflight_cancels(reason: str) -> None:
            for work in list(inflight.values()):
                if work.handle is not None:
                    self._fence_cancel_handle(work.handle, reason=reason)

        def _try_admit(node_id: str) -> bool:
            self._bump_owning_loop()
            if node_id not in pending or node_id in node_runs:
                return False
            fanin = fanin_for(node_id)
            if fanin.unsettled or fanin.halt:
                return False
            _record_park_end(node_id)
            if complete_replay(node_id, fanin):
                return True
            if try_cache_hit(node_id, fanin):
                return True
            inflight_claims = self._inflight_claims(inflight, claims_by_id)
            gate_hits = contends_with_inflight(
                claims_by_id[node_id], inflight_claims
            )
            if gate_hits:
                _park_node(node_id, TimingCategory.CONTENTION_WAIT)
                if node_id not in parked_ids:
                    parked_ids.append(node_id)
                return False
            node = by_id[node_id]
            pool = PoolName(node["resources"]["pool"])
            slots = int(node["resources"]["slots"])
            try:
                self._pools.acquire(pool, slots=slots, node_id=node_id)
            except PoolRequestUnsatisfiable as exc:
                raise SchedulerError(
                    f"node {node_id}: unsatisfiable pool request at dispatch"
                ) from exc
            except PoolExhausted:
                _park_node(node_id, TimingCategory.RESOURCE_WAIT)
                if node_id not in parked_ids:
                    parked_ids.append(node_id)
                return False
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
            bk_start = self._clock()
            self._receipts.begin(
                node_id,
                f"{run_id}:{graph_hash}:{node_id}",
                intent,
            )
            timing.record_bookkeeping(
                int((self._clock() - bk_start) * 1000), detail="receipt-begin"
            )
            work = _InflightWork(
                node_id=node_id,
                fanin=fanin,
                pool=pool,
                slots=slots,
            )
            inflight[node_id] = work
            parked_ids[:] = [item for item in parked_ids if item != node_id]
            self._start_worker(
                work,
                node=node,
                run_id=run_id,
                graph_hash=graph_hash,
                predecessors=predecessors,
                output_hashes=output_hashes,
                write_paths=write_paths,
                compiled=compiled,
                started_at=started_at,
                max_duration=max_duration,
            )
            return True

        max_observed_inflight = 0
        self._state_owner_thread = threading.get_ident()
        loop_done = False
        try:
            while pending or inflight:
                self._bump_owning_loop()

                if max_duration is not None and (
                    self._clock() - started_at
                ) > max_duration:
                    _cancel_pending(f"maxDurationSeconds={max_duration}")
                    _fence_inflight_cancels(
                        f"maxDurationSeconds={max_duration}"
                    )
                    applied_cancel = CancelMode.CANCEL_AND_DRAIN
                    if not inflight:
                        loop_done = True
                        break

                if self._cancel_requested is CancelMode.CANCEL_AND_DRAIN:
                    _cancel_pending("cancel-and-drain")
                    _fence_inflight_cancels("cancel-and-drain")
                    applied_cancel = CancelMode.CANCEL_AND_DRAIN
                    if not inflight:
                        loop_done = True
                        break

                if (
                    self._cancel_requested is CancelMode.LET_SETTLE
                    and not inflight
                ):
                    applied_cancel = CancelMode.LET_SETTLE
                    _cancel_pending("let-settle-no-new-admission")
                    loop_done = True
                    break

                drained = False
                while True:
                    try:
                        event = self._event_queue.get_nowait()
                    except queue.Empty:
                        break
                    drained = True
                    _process_completion(event)

                if loop_done:
                    break

                if max_duration is not None and (
                    self._clock() - started_at
                ) > max_duration:
                    _cancel_pending(f"maxDurationSeconds={max_duration}")
                    _fence_inflight_cancels(
                        f"maxDurationSeconds={max_duration}"
                    )
                    applied_cancel = CancelMode.CANCEL_AND_DRAIN
                    if not inflight:
                        loop_done = True
                        break
                    continue

                if self._cancel_requested is CancelMode.LET_SETTLE:
                    if inflight:
                        if not drained:
                            _process_completion(self._event_queue.get())
                        continue
                    applied_cancel = CancelMode.LET_SETTLE
                    _cancel_pending("let-settle-no-new-admission")
                    break

                ready = ready_set()
                admitted = 0
                if self._cancel_requested not in (
                    CancelMode.LET_SETTLE,
                    CancelMode.CANCEL_AND_DRAIN,
                ):
                    for node_id in ready:
                        if len(inflight) >= max_conc:
                            _park_node(node_id, TimingCategory.QUEUE_WAIT)
                            break
                        if _try_admit(node_id):
                            admitted += 1
                    max_observed_inflight = max(max_observed_inflight, len(inflight))

                flush_snapshot(queue=ready)

                if not pending and not inflight:
                    break

                if admitted == 0 and inflight:
                    if not drained:
                        _process_completion(self._event_queue.get())
                    continue

                if admitted == 0 and not inflight:
                    if parked_ids:
                        raise SchedulerNoProgress(
                            list(parked_ids), reason="pool-parked-no-progress"
                        )
                    raise SchedulerNoProgress(
                        sorted(pending, key=source_order.__getitem__),
                        reason="no-progress",
                    )
        except BaseException:
            for work in list(inflight.values()):
                _release_inflight(work)
                self._release_lease(work.node_id)
            flush_snapshot()
            raise
        finally:
            self._state_owner_thread = None

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
                "maxObservedInflight": max_observed_inflight,
                "timingEventCount": len(timing.events),
            }
        )
        verdict = (
            "pass"
            if all(item.verdict == "pass" for item in ordered_runs)
            and redetect_failure is None
            else "fail"
        )
        if redetect_context is not None and redetect_state is not None and redetect_failure is None:
            final_redetect = merge_gate_redetect(
                changed_paths=redetect_state.changed_paths,
                dispatched=redetect_state,
                satisfied_capability_ids=redetect_context.satisfied_capability_ids,
            )
            redetect_verdict = final_redetect
            if final_redetect.verdict != "pass":
                verdict = "fail"
        return SchedulerRun(
            run_id=run_id,
            graph_hash=graph_hash,
            verdict=verdict,
            nodes=ordered_runs,
            receipts=tuple(persisted_receipts),
            contention_findings=contention,
            pool_snapshot=self._pools.snapshot(),
            cancel_mode=None if applied_cancel is None else applied_cancel.value,
            timing_events=timing.events,
            redetect=redetect_verdict,
        )
