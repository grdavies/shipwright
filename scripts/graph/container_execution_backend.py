#!/usr/bin/env python3
"""OCI container ExecutionBackend with broker-only credentials (PRD 279 R3–R7)."""
from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from graph.execution_backend import (
    AdvisoryExecutionReport,
    ExecutionBackendError,
    ExecutionHandle,
    HostExecutionHints,
    PollPhase,
    PollStatus,
    SubmitRequest,
    SubmitResult,
    TerminalEnvelope,
)

Clock = Callable[[], float]


class ContainerRuntimePhase(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    TERMINAL = "terminal"


@dataclass(frozen=True)
class ContainerResourceLimits:
    memory_mb: int = 512
    cpu_millis: int = 1000
    timeout_seconds: int = 3600


@dataclass(frozen=True)
class ContainerExecutionConfig:
    image: str = "shipwright/graph-node:latest"
    credential_ref: str | None = None
    resource_limits: ContainerResourceLimits = field(default_factory=ContainerResourceLimits)
    store_root: Path | None = None


@dataclass
class _RuntimeState:
    container_id: str
    phase: ContainerRuntimePhase = ContainerRuntimePhase.PENDING
    exit_code: int | None = None
    output: Any = None
    cancel_requested: bool = False
    cancel_acknowledged: bool = False


@runtime_checkable
class ContainerRuntime(Protocol):
    """Minimal OCI lifecycle surface for container node execution."""

    def submit(
        self,
        *,
        image: str,
        node: Mapping[str, Any],
        resource_limits: ContainerResourceLimits,
        credential_env: Mapping[str, str],
    ) -> str: ...

    def poll(self, container_id: str) -> _RuntimeState: ...

    def cancel(self, container_id: str) -> _RuntimeState: ...


class MockContainerRuntime:
    """Hermetic runtime for unit/conformance tests — no external OCI dependency."""

    def __init__(self, *, delay_s: float = 0.0, clock: Clock | None = None) -> None:
        self._delay = delay_s
        self._clock = clock or time.monotonic
        self._states: dict[str, _RuntimeState] = {}
        self._lock = threading.Lock()

    def submit(
        self,
        *,
        image: str,
        node: Mapping[str, Any],
        resource_limits: ContainerResourceLimits,
        credential_env: Mapping[str, str],
    ) -> str:
        container_id = f"mock-{uuid.uuid4().hex[:12]}"
        state = _RuntimeState(container_id=container_id)
        self._states[container_id] = state

        def _run() -> None:
            if self._delay:
                time.sleep(self._delay)
            with self._lock:
                current = self._states.get(container_id)
                if current is None or current.cancel_requested:
                    return
                current.phase = ContainerRuntimePhase.RUNNING
            if self._delay:
                time.sleep(self._delay)
            with self._lock:
                current = self._states.get(container_id)
                if current is None or current.cancel_requested:
                    return
                current.phase = ContainerRuntimePhase.TERMINAL
                current.exit_code = 0
                current.output = {
                    "nodeId": node.get("id"),
                    "image": image,
                    "credentialKeys": sorted(credential_env.keys()),
                    "memoryMb": resource_limits.memory_mb,
                }

        with self._lock:
            state.phase = ContainerRuntimePhase.PENDING
        threading.Thread(target=_run, daemon=True).start()
        return container_id

    def poll(self, container_id: str) -> _RuntimeState:
        with self._lock:
            state = self._states.get(container_id)
            if state is None:
                raise ExecutionBackendError(f"unknown container: {container_id}")
            return _RuntimeState(
                container_id=state.container_id,
                phase=state.phase,
                exit_code=state.exit_code,
                output=state.output,
                cancel_requested=state.cancel_requested,
                cancel_acknowledged=state.cancel_acknowledged,
            )

    def cancel(self, container_id: str) -> _RuntimeState:
        with self._lock:
            state = self._states.get(container_id)
            if state is None:
                raise ExecutionBackendError(f"unknown container: {container_id}")
            state.cancel_requested = True
            state.cancel_acknowledged = True
            if state.phase != ContainerRuntimePhase.TERMINAL:
                state.phase = ContainerRuntimePhase.TERMINAL
                state.exit_code = 137
                state.output = {"cancelled": True}
            return _RuntimeState(
                container_id=state.container_id,
                phase=state.phase,
                exit_code=state.exit_code,
                output=state.output,
                cancel_requested=True,
                cancel_acknowledged=True,
            )


@dataclass
class _DurableHandle:
    handle_id: str
    idempotency_key: str
    generation: int
    phase: str
    container_id: str | None = None
    cancel_requested: bool = False
    cancel_acknowledged: bool = False
    terminal: dict[str, Any] | None = None
    request: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> _DurableHandle:
        return cls(
            handle_id=str(payload["handle_id"]),
            idempotency_key=str(payload["idempotency_key"]),
            generation=int(payload.get("generation") or 1),
            phase=str(payload.get("phase") or PollPhase.PENDING.value),
            container_id=payload.get("container_id"),
            cancel_requested=bool(payload.get("cancel_requested")),
            cancel_acknowledged=bool(payload.get("cancel_acknowledged")),
            terminal=payload.get("terminal"),
            request=dict(payload.get("request") or {}),
        )


class ContainerHandleStore:
    """Durable handle journal for crash recovery and idempotency (R4/R6)."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)
        self._path = self._root / "handles.json"
        self._lock = threading.Lock()
        self._handles: dict[str, _DurableHandle] = {}
        self._by_idempotency: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.is_file():
            return
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        for raw in payload.get("handles") or []:
            handle = _DurableHandle.from_dict(raw)
            self._handles[handle.handle_id] = handle
            self._by_idempotency[handle.idempotency_key] = handle.handle_id

    def _persist(self) -> None:
        doc = {"handles": [handle.to_dict() for handle in self._handles.values()]}
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, sort_keys=True), encoding="utf-8")
        tmp.replace(self._path)

    def get_by_idempotency(self, idempotency_key: str) -> _DurableHandle | None:
        handle_id = self._by_idempotency.get(idempotency_key)
        if handle_id is None:
            return None
        return self._handles.get(handle_id)

    def get(self, handle_id: str) -> _DurableHandle | None:
        return self._handles.get(handle_id)

    def put(self, handle: _DurableHandle) -> None:
        with self._lock:
            self._handles[handle.handle_id] = handle
            self._by_idempotency[handle.idempotency_key] = handle.handle_id
            self._persist()

    def mutate(
        self,
        handle_id: str,
        *,
        generation: int,
        mutator: Callable[[_DurableHandle], None],
    ) -> _DurableHandle:
        with self._lock:
            handle = self._handles.get(handle_id)
            if handle is None:
                raise ExecutionBackendError(f"unknown handle: {handle_id}")
            if handle.generation != generation:
                raise ExecutionBackendError(
                    f"generation fence refused mutation for {handle_id}: "
                    f"expected {generation}, have {handle.generation}"
                )
            mutator(handle)
            self._persist()
            return handle


def resolve_container_execution_config(
    cfg: Mapping[str, Any],
    *,
    root: Path | None = None,
) -> ContainerExecutionConfig:
    graph_exec = cfg.get("graphExecution") or {}
    execution = graph_exec.get("execution") or {}
    container = execution.get("container") or {}
    limits_raw = container.get("resourceLimits") or {}
    store_raw = container.get("storeRoot")
    store_root = Path(store_raw) if store_raw else None
    if store_root is None and root is not None:
        store_root = root / ".cursor" / "sw-graph-runs" / "container-handles"
    return ContainerExecutionConfig(
        image=str(container.get("image") or "shipwright/graph-node:latest"),
        credential_ref=container.get("credentialRef"),
        resource_limits=ContainerResourceLimits(
            memory_mb=int(limits_raw.get("memoryMb") or 512),
            cpu_millis=int(limits_raw.get("cpuMillis") or 1000),
            timeout_seconds=int(limits_raw.get("timeoutSeconds") or 3600),
        ),
        store_root=store_root,
    )


def _resolve_credential_env(
    config: ContainerExecutionConfig,
    *,
    root: Path | None,
    broker: Callable[[str, Path], Mapping[str, str]] | None = None,
) -> Mapping[str, str]:
    if not config.credential_ref:
        return {}
    if broker is not None:
        return broker(config.credential_ref, root or Path.cwd())
    from credentials.model import CredentialRef, ResolutionState
    from credentials.resolver import RepositoryContext, resolve
    from host_lib import (
        detect_provider_from_url,
        git_remote_url,
        load_workflow_config,
        parse_owner_repo,
        remote_name,
    )

    repo_root = root or Path.cwd()
    cfg = load_workflow_config(repo_root)
    project_id = cfg.get("projectId")
    project_id_str = (
        project_id.strip()
        if isinstance(project_id, str) and project_id.strip()
        else "unpaired"
    )
    remote = remote_name(cfg)
    remote_url = git_remote_url(repo_root, remote)
    parsed = parse_owner_repo(remote_url if isinstance(remote_url, str) else None)
    repo_slug = f"{parsed[0]}/{parsed[1]}" if parsed else ""
    provider = detect_provider_from_url(remote_url) if remote_url else "shipwright"
    if provider == "none":
        provider = "shipwright"
    ref = CredentialRef(config.credential_ref.strip())
    context = RepositoryContext(
        remote=remote_url or remote,
        repo_slug=repo_slug,
        project_id=project_id_str,
        destination_endpoint="https://localhost",
    )
    resolution = resolve(
        ref,
        provider=provider,
        purpose="graph-container-exec",
        context=context,
    )
    if resolution.state is not ResolutionState.RESOLVED or resolution.token is None:
        reason = resolution.reason or "container-credential-unresolved"
        raise ExecutionBackendError(
            f"credential broker refused container execution: {reason}"
        )
    return {"GRAPH_CONTAINER_TOKEN": resolution.token.token.value}


def _validate_mutating_gates(
    request: SubmitRequest,
    *,
    config: ContainerExecutionConfig,
    root: Path | None,
    credential_resolver: Callable[[str, Path], Mapping[str, str]] | None = None,
) -> None:
    """R7: mutating nodes require capability token and broker-resolved credentials."""
    if not request.host_hints.mutating:
        return
    if not str(request.capability_token or "").strip():
        raise ExecutionBackendError(
            "mutating container node refused: missing capability_token"
        )
    if config.credential_ref:
        _resolve_credential_env(
            config,
            root=root,
            broker=credential_resolver,
        )


def _runtime_phase_to_poll(state: _RuntimeState, handle: _DurableHandle) -> PollPhase:
    if handle.cancel_acknowledged:
        return PollPhase.CANCEL_ACKNOWLEDGED
    if handle.cancel_requested and not handle.cancel_acknowledged:
        return PollPhase.CANCEL_REQUESTED
    if state.phase == ContainerRuntimePhase.TERMINAL:
        return PollPhase.TERMINAL
    if state.phase == ContainerRuntimePhase.RUNNING:
        return PollPhase.RUNNING
    return PollPhase.PENDING


class ContainerExecutionBackend:
    """OCI-backed ExecutionBackend with durable handles and generation fencing."""

    def __init__(
        self,
        *,
        config: ContainerExecutionConfig,
        runtime: ContainerRuntime | None = None,
        store: ContainerHandleStore | None = None,
        root: Path | None = None,
        credential_resolver: Callable[[str, Path], Mapping[str, str]] | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._config = config
        self._runtime = runtime or MockContainerRuntime(clock=clock)
        store_root = config.store_root or (root or Path.cwd()) / ".cursor/sw-graph-runs/container-handles"
        self._store = store or ContainerHandleStore(store_root)
        self._root = root
        self._credential_resolver = credential_resolver
        self._clock = clock or time.monotonic
        self._generation = 1

    def submit(self, request: SubmitRequest) -> SubmitResult:
        _validate_mutating_gates(
            request,
            config=self._config,
            root=self._root,
            credential_resolver=self._credential_resolver,
        )

        existing = self._store.get_by_idempotency(request.idempotency_key)
        if existing is not None:
            return SubmitResult(
                handle=ExecutionHandle(existing.handle_id, request.idempotency_key),
                duplicate=True,
            )

        handle_id = str(uuid.uuid4())
        generation = self._generation
        self._generation += 1

        credential_env: Mapping[str, str] = {}
        if self._config.credential_ref and request.host_hints.mutating:
            credential_env = _resolve_credential_env(
                self._config,
                root=self._root,
                broker=self._credential_resolver,
            )

        container_id = self._runtime.submit(
            image=self._config.image,
            node=dict(request.node),
            resource_limits=self._config.resource_limits,
            credential_env=credential_env,
        )

        handle = _DurableHandle(
            handle_id=handle_id,
            idempotency_key=request.idempotency_key,
            generation=generation,
            phase=PollPhase.RUNNING.value,
            container_id=container_id,
            request={
                "node": dict(request.node),
                "mutating": request.host_hints.mutating,
                "purity": request.host_hints.purity,
            },
        )
        self._store.put(handle)
        return SubmitResult(
            handle=ExecutionHandle(handle_id, request.idempotency_key),
            duplicate=False,
        )

    def poll(self, handle: ExecutionHandle) -> PollStatus:
        record = self._require(handle)
        if record.terminal is not None:
            return PollStatus(
                phase=PollPhase.TERMINAL,
                cancel_acknowledged=record.cancel_acknowledged,
            )
        if record.container_id is None:
            raise ExecutionBackendError(f"orphan handle missing container: {handle.handle_id}")

        try:
            runtime_state = self._runtime.poll(record.container_id)
        except ExecutionBackendError:
            self._store.mutate(
                record.handle_id,
                generation=record.generation,
                mutator=lambda h: self._finalize_orphan(h),
            )
            return PollStatus(phase=PollPhase.TERMINAL)

        poll_phase = _runtime_phase_to_poll(runtime_state, record)

        if poll_phase == PollPhase.TERMINAL and record.terminal is None:
            self._store.mutate(
                record.handle_id,
                generation=record.generation,
                mutator=lambda h: self._finalize_terminal(h, runtime_state),
            )

        return PollStatus(
            phase=poll_phase,
            cancel_acknowledged=record.cancel_acknowledged,
        )

    def cancel(self, handle: ExecutionHandle) -> PollStatus:
        record = self._require(handle)

        def _mark_cancel_requested(target: _DurableHandle) -> None:
            target.cancel_requested = True

        self._store.mutate(
            record.handle_id,
            generation=record.generation,
            mutator=_mark_cancel_requested,
        )

        if record.container_id is not None:
            runtime_state = self._runtime.cancel(record.container_id)
        else:
            runtime_state = _RuntimeState(
                container_id="orphan",
                phase=ContainerRuntimePhase.TERMINAL,
                exit_code=137,
                output={"cancelled": True},
                cancel_requested=True,
                cancel_acknowledged=True,
            )

        def _mark_cancel_ack(target: _DurableHandle) -> None:
            target.cancel_acknowledged = True
            target.phase = PollPhase.CANCEL_ACKNOWLEDGED.value
            self._finalize_terminal(target, runtime_state, reason="cancel-acknowledged")

        updated = self._store.mutate(
            record.handle_id,
            generation=record.generation,
            mutator=_mark_cancel_ack,
        )
        return PollStatus(
            phase=PollPhase.CANCEL_ACKNOWLEDGED,
            cancel_acknowledged=updated.cancel_acknowledged,
        )

    def result(self, handle: ExecutionHandle) -> TerminalEnvelope:
        record = self._require(handle)
        if record.terminal is None:
            raise ExecutionBackendError(f"handle not terminal: {handle.handle_id}")
        report_raw = record.terminal.get("report") or {}
        return TerminalEnvelope(
            report=AdvisoryExecutionReport(**report_raw),
            output_hash=record.terminal.get("output_hash"),
            reason=str(record.terminal.get("reason") or ""),
        )

    def _require(self, handle: ExecutionHandle) -> _DurableHandle:
        record = self._store.get(handle.handle_id)
        if record is None:
            raise ExecutionBackendError(f"unknown handle: {handle.handle_id}")
        if record.idempotency_key != handle.idempotency_key:
            raise ExecutionBackendError("handle/idempotency_key mismatch")
        return record

    def _finalize_orphan(self, handle: _DurableHandle) -> None:
        handle.phase = PollPhase.TERMINAL.value
        handle.terminal = {
            "report": {
                "verdict": "fail",
                "output": {"orphanRecovered": True},
                "model": "container-runtime",
                "coverage": {"orphanHandleRecovery": True},
            },
            "reason": "orphan-handle-recovery",
        }

    def _finalize_terminal(
        self,
        handle: _DurableHandle,
        runtime_state: _RuntimeState,
        *,
        reason: str = "",
    ) -> None:
        if runtime_state.cancel_acknowledged or handle.cancel_acknowledged:
            verdict = "cancelled"
            coverage = {"cancelled": True}
        elif runtime_state.exit_code == 0:
            verdict = "pass"
            coverage = {"containerId": runtime_state.container_id}
        else:
            verdict = "fail"
            coverage = {
                "containerId": runtime_state.container_id,
                "exitCode": runtime_state.exit_code,
            }
        handle.phase = PollPhase.TERMINAL.value
        handle.terminal = {
            "report": {
                "verdict": verdict,
                "output": runtime_state.output,
                "model": "container-runtime",
                "coverage": coverage,
            },
            "reason": reason,
        }
