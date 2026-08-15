#!/usr/bin/env python3
"""ExecutionBackend protocol and host-authoritative result adjudication (PRD 271 R9/R10)."""
from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from graph.scheduler import NodeExecutionResult


class ExecutionBackendError(RuntimeError):
    """Raised when backend contract boundaries are violated."""


class KernelAuthorityViolation(ExecutionBackendError):
    """Raised when a backend attempts to set host-authoritative fields."""


# Host derives these; backend-reported copies are advisory only (R10).
KERNEL_AUTHORITY_FIELDS = frozenset(
    {
        "scope_identity",
        "resolved_scope_identity",
        "repository_identity",
        "trust_domain",
        "repo_state_identity",
        "tool_binary_identity",
        "credential_capabilities",
        "credential_capability_set",
        "prompt_version",
        "model_version",
        "policy_version",
        "tool_configuration",
        "purity",
        "wrote",
        "duration_ms",
        "durationMs",
        "verdict_eligible",
        "cache_key",
        "cacheKey",
    }
)


class PollPhase(str, Enum):
    """Non-terminal backend lifecycle phases."""

    PENDING = "pending"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel-requested"
    CANCEL_ACKNOWLEDGED = "cancel-acknowledged"
    TERMINAL = "terminal"


@dataclass(frozen=True)
class ExecutionHandle:
    """Durable opaque handle returned by submit (R9)."""

    handle_id: str
    idempotency_key: str


@dataclass(frozen=True)
class HostExecutionHints:
    """Host-derived execution hints passed to backends; not overridable (R10)."""

    mutating: bool
    purity: str


@dataclass(frozen=True)
class SubmitRequest:
    """Least-required context for backend dispatch (R10)."""

    idempotency_key: str
    node: Mapping[str, Any]
    capability_token: str
    input_hashes: tuple[str, ...]
    host_hints: HostExecutionHints


@dataclass(frozen=True)
class SubmitResult:
    """Idempotent submit acknowledgement."""

    handle: ExecutionHandle
    duplicate: bool = False


@dataclass(frozen=True)
class PollStatus:
    """Poll/events envelope before terminal settlement."""

    phase: PollPhase
    cancel_acknowledged: bool = False


@dataclass(frozen=True)
class AdvisoryExecutionReport:
    """Backend-reported values — advisory only (R10)."""

    verdict: str = "pass"
    output: Any = None
    model: str = "unknown"
    attempts: int = 1
    tokens: int = 0
    duration_ms: int = 0
    coverage: Mapping[str, Any] = field(default_factory=dict)
    wrote: bool = False
    retry_only: bool = False
    scope_identity: str = ""
    repository_identity: str = ""
    trust_domain: str = ""
    repo_state_identity: str = ""
    tool_binary_identity: str = ""
    credential_capabilities: tuple[str, ...] = ()
    prompt_version: str = ""
    model_version: str = ""
    policy_version: str = ""
    tool_configuration: Mapping[str, Any] = field(default_factory=dict)
    purity: str = ""
    verdict_eligible: bool = True


@dataclass(frozen=True)
class TerminalEnvelope:
    """Terminal execution envelope from a backend."""

    report: AdvisoryExecutionReport
    output_hash: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class HostAdjudicationContext:
    """Host-authoritative execution context for result settlement."""

    node_id: str
    idempotency_key: str
    mutating: bool
    purity: str
    cache_identity: Mapping[str, Any]
    started_at_monotonic: float
    input_hashes: tuple[str, ...] = ()


@dataclass(frozen=True)
class AdjudicatedExecutionResult:
    """Host-settled execution result."""

    verdict: str
    output: Any
    model: str
    attempts: int
    tokens: int
    duration_ms: int
    coverage: Mapping[str, Any]
    wrote: bool
    retry_only: bool
    cache_identity: Mapping[str, Any]
    purity: str
    advisory_ignored_fields: tuple[str, ...] = ()

    def to_node_execution_result(self) -> NodeExecutionResult:
        from graph.scheduler import NodeExecutionResult

        identity = dict(self.cache_identity)
        return NodeExecutionResult(
            verdict=self.verdict,
            output=self.output,
            model=self.model,
            attempts=self.attempts,
            tokens=self.tokens,
            duration_ms=self.duration_ms,
            coverage=dict(self.coverage),
            wrote=self.wrote,
            retry_only=self.retry_only,
            prompt_version=str(identity.get("prompt_version") or "default"),
            model_version=str(
                identity.get("model_version") or identity.get("model") or "default"
            ),
            tool_configuration=dict(identity.get("tool_configuration") or {}),
            policy_version=str(identity.get("policy_version") or "default"),
            credential_capabilities=tuple(
                identity.get("credential_capabilities")
                or identity.get("credential_capability_set")
                or ()
            ),
            scope_identity=str(identity.get("scope_identity") or "default"),
            repository_identity=str(identity.get("repository_identity") or "default"),
            trust_domain=str(identity.get("trust_domain") or "default"),
            tool_binary_identity=str(identity.get("tool_binary_identity") or "default"),
            repo_state_identity=str(identity.get("repo_state_identity") or "default"),
        )


Clock = type(time.monotonic)


def _report_as_mapping(report: AdvisoryExecutionReport) -> dict[str, Any]:
    return {
        "verdict": report.verdict,
        "output": report.output,
        "model": report.model,
        "attempts": report.attempts,
        "tokens": report.tokens,
        "duration_ms": report.duration_ms,
        "coverage": dict(report.coverage),
        "wrote": report.wrote,
        "retry_only": report.retry_only,
        "scope_identity": report.scope_identity,
        "repository_identity": report.repository_identity,
        "trust_domain": report.trust_domain,
        "repo_state_identity": report.repo_state_identity,
        "tool_binary_identity": report.tool_binary_identity,
        "credential_capabilities": report.credential_capabilities,
        "prompt_version": report.prompt_version,
        "model_version": report.model_version,
        "policy_version": report.policy_version,
        "tool_configuration": dict(report.tool_configuration),
        "purity": report.purity,
        "verdict_eligible": report.verdict_eligible,
    }


def strip_kernel_authority_fields(
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Remove kernel-authority keys from an advisory payload; return stripped + violations."""
    stripped: dict[str, Any] = {}
    violations: list[str] = []
    for key, value in payload.items():
        if key in KERNEL_AUTHORITY_FIELDS:
            violations.append(key)
            continue
        stripped[key] = value
    return stripped, tuple(violations)


def refuse_kernel_authority_fields(payload: Mapping[str, Any]) -> None:
    """Fail closed when a backend sets host-authoritative fields (R10)."""
    violations = [key for key in payload if key in KERNEL_AUTHORITY_FIELDS]
    if violations:
        raise KernelAuthorityViolation(
            f"backend attempted kernel-authority fields: {', '.join(sorted(violations))}"
        )


def host_cache_identity(
    host: HostAdjudicationContext,
    *,
    result: NodeExecutionResult | None = None,
) -> dict[str, Any]:
    """Derive cache identity from host context only — never backend advisory (R10)."""
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
    base.update(dict(host.cache_identity))
    if result is not None:
        # Host scheduler identity still wins over executor defaults.
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
                "credential_capabilities": tuple(result.credential_capabilities),
                "scope_identity": result.scope_identity,
                "repository_identity": result.repository_identity,
                "trust_domain": result.trust_domain,
                "tool_binary_identity": result.tool_binary_identity,
                "repo_state_identity": result.repo_state_identity,
            }
        )
        base.update(dict(host.cache_identity))
    return base


def adjudicate_terminal_envelope(
    host: HostAdjudicationContext,
    envelope: TerminalEnvelope,
    *,
    clock: Clock | None = None,
) -> AdjudicatedExecutionResult:
    """Settle a terminal backend envelope under host authority (R9/R10)."""
    clock_fn = clock or time.monotonic
    report = envelope.report
    host_duration_ms = max(0, int((clock_fn() - host.started_at_monotonic) * 1000))
    ignored: list[str] = []
    for field_name in KERNEL_AUTHORITY_FIELDS:
        if getattr(report, field_name, None) in (None, "", (), {}, False):
            continue
        if field_name in {"duration_ms", "durationMs"} and report.duration_ms:
            ignored.append("duration_ms")
        elif field_name == "purity" and report.purity:
            ignored.append("purity")
        elif field_name == "wrote" and report.wrote:
            ignored.append("wrote")
        elif field_name in {
            "scope_identity",
            "repository_identity",
            "trust_domain",
            "repo_state_identity",
            "tool_binary_identity",
            "credential_capabilities",
            "credential_capability_set",
            "prompt_version",
            "model_version",
            "policy_version",
            "tool_configuration",
        }:
            if getattr(report, field_name, None):
                ignored.append(field_name)

    verdict = report.verdict if report.verdict_eligible else "fail"
    if not report.verdict_eligible:
        ignored.append("verdict")

    from graph.scheduler import NodeExecutionResult

    provisional = NodeExecutionResult(
        verdict=verdict,
        output=report.output,
        model=report.model,
        attempts=report.attempts,
        tokens=report.tokens,
        duration_ms=host_duration_ms,
        coverage=dict(report.coverage),
        wrote=report.wrote if host.purity == "mutating" else False,
        retry_only=report.retry_only,
        scope_identity=report.scope_identity or "default",
        repository_identity=report.repository_identity or "default",
        trust_domain=report.trust_domain or "default",
        tool_binary_identity=report.tool_binary_identity or "default",
        repo_state_identity=report.repo_state_identity or "default",
        prompt_version=report.prompt_version or "default",
        model_version=report.model_version or report.model,
        policy_version=report.policy_version or "default",
        tool_configuration=dict(report.tool_configuration),
        credential_capabilities=report.credential_capabilities,
    )
    identity = host_cache_identity(host, result=provisional)
    return AdjudicatedExecutionResult(
        verdict=verdict,
        output=report.output,
        model=report.model,
        attempts=report.attempts,
        tokens=report.tokens,
        duration_ms=host_duration_ms,
        coverage=dict(report.coverage),
        wrote=host.mutating and bool(report.wrote),
        retry_only=report.retry_only,
        cache_identity=identity,
        purity=host.purity,
        advisory_ignored_fields=tuple(sorted(set(ignored))),
    )


@runtime_checkable
class ExecutionBackend(Protocol):
    """Minimal backend contract: submit / poll / cancel / result (R9)."""

    def submit(self, request: SubmitRequest) -> SubmitResult: ...

    def poll(self, handle: ExecutionHandle) -> PollStatus: ...

    def cancel(self, handle: ExecutionHandle) -> PollStatus: ...

    def result(self, handle: ExecutionHandle) -> TerminalEnvelope: ...


@dataclass
class _HandleRecord:
    request: SubmitRequest
    phase: PollPhase
    terminal: TerminalEnvelope | None = None
    cancel_requested: bool = False
    cancel_acknowledged: bool = False


class InMemoryExecutionBackend:
    """Test/dogfood backend with durable in-memory handles (R9)."""

    def __init__(
        self,
        runner: Any,
        *,
        durable_path: Any | None = None,
    ) -> None:
        self._runner = runner
        self._records: dict[str, _HandleRecord] = {}
        self._by_idempotency: dict[str, str] = {}
        self._durable_path = durable_path

    def submit(self, request: SubmitRequest) -> SubmitResult:
        existing = self._by_idempotency.get(request.idempotency_key)
        if existing is not None:
            return SubmitResult(
                handle=ExecutionHandle(existing, request.idempotency_key),
                duplicate=True,
            )

        handle_id = str(uuid.uuid4())
        record = _HandleRecord(request=request, phase=PollPhase.RUNNING)
        self._records[handle_id] = record
        self._by_idempotency[request.idempotency_key] = handle_id

        report = self._runner(request)
        if isinstance(report, TerminalEnvelope):
            record.terminal = report
        else:
            if isinstance(report, AdvisoryExecutionReport):
                record.terminal = TerminalEnvelope(report=report)
            else:
                refuse_kernel_authority_fields(report)
                record.terminal = TerminalEnvelope(
                    report=AdvisoryExecutionReport(**report)
                )
        record.phase = PollPhase.TERMINAL
        return SubmitResult(
            handle=ExecutionHandle(handle_id, request.idempotency_key),
            duplicate=False,
        )

    def poll(self, handle: ExecutionHandle) -> PollStatus:
        record = self._require(handle)
        if record.cancel_acknowledged:
            return PollStatus(
                phase=PollPhase.CANCEL_ACKNOWLEDGED,
                cancel_acknowledged=True,
            )
        if record.phase == PollPhase.TERMINAL:
            return PollStatus(phase=PollPhase.TERMINAL)
        if record.cancel_requested:
            return PollStatus(phase=PollPhase.CANCEL_REQUESTED)
        return PollStatus(phase=record.phase)

    def cancel(self, handle: ExecutionHandle) -> PollStatus:
        record = self._require(handle)
        record.cancel_requested = True
        record.cancel_acknowledged = True
        if record.terminal is None:
            record.terminal = TerminalEnvelope(
                report=AdvisoryExecutionReport(
                    verdict="cancelled",
                    coverage={"cancelled": True},
                ),
                reason="cancel-acknowledged",
            )
            record.phase = PollPhase.TERMINAL
        return PollStatus(
            phase=PollPhase.CANCEL_ACKNOWLEDGED,
            cancel_acknowledged=True,
        )

    def result(self, handle: ExecutionHandle) -> TerminalEnvelope:
        record = self._require(handle)
        if record.terminal is None:
            raise ExecutionBackendError(f"handle not terminal: {handle.handle_id}")
        return record.terminal

    def _require(self, handle: ExecutionHandle) -> _HandleRecord:
        record = self._records.get(handle.handle_id)
        if record is None:
            raise ExecutionBackendError(f"unknown handle: {handle.handle_id}")
        if record.request.idempotency_key != handle.idempotency_key:
            raise ExecutionBackendError("handle/idempotency_key mismatch")
        return record


class LocalSyncExecutionBackend:
    """Local synchronous backend wrapping a node executor (R9)."""

    def __init__(
        self,
        executor: Any,
        *,
        clock: Clock | None = None,
    ) -> None:
        self._inner = InMemoryExecutionBackend(self._execute, durable_path=None)
        self._executor = executor
        self._clock = clock or time.monotonic

    def _execute(self, request: SubmitRequest) -> AdvisoryExecutionReport:
        from graph.scheduler import NodeExecutionResult

        started = self._clock()
        raw = self._executor(dict(request.node))
        if not isinstance(raw, NodeExecutionResult):
            raise ExecutionBackendError("executor returned invalid NodeExecutionResult")
        elapsed = max(
            raw.duration_ms,
            max(0, int((self._clock() - started) * 1000)),
        )
        return AdvisoryExecutionReport(
            verdict=raw.verdict,
            output=raw.output,
            model=raw.model,
            attempts=raw.attempts,
            tokens=raw.tokens,
            duration_ms=elapsed,
            coverage=dict(raw.coverage),
            wrote=raw.wrote,
            retry_only=raw.retry_only,
        )

    def submit(self, request: SubmitRequest) -> SubmitResult:
        return self._inner.submit(request)

    def poll(self, handle: ExecutionHandle) -> PollStatus:
        return self._inner.poll(handle)

    def cancel(self, handle: ExecutionHandle) -> PollStatus:
        return self._inner.cancel(handle)

    def result(self, handle: ExecutionHandle) -> TerminalEnvelope:
        return self._inner.result(handle)
